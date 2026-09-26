"""
Medpark Meeting Intelligence System - Local LLM Client
Thin async client for the Ollama native API (health, provenance, constrained JSON completion, unload).
"""

import asyncio
import json
import time
import httpx
from app.core.config import settings
from app.core.exceptions import ExtractionError, LLMUnavailable
from app.core.logging import logger


class OllamaClient:
    """
    Talks to a locally running Ollama server. Health checks never load the model; every
    completion is deterministic (temperature from settings, top_k 1, explicit seed) and
    grammar-constrained by a JSON Schema so message.content is always parseable JSON.
    """

    def __init__(self, base_url: str, model: str, timeout_s: float, health_timeout_s: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.health_timeout_s = health_timeout_s
        self._logged_provenance: str | None = None

    def _model_matches(self, name: str) -> bool:
        # /api/tags reports "medpark-extractor:latest" for an untagged alias
        return name == self.model or name == f"{self.model}:latest" or name.split(":")[0] == self.model

    async def health(self) -> tuple[bool, str]:
        """GET /api/version and GET /api/tags only: reports (connected AND model installed, reason). Never loads the model."""
        try:
            async with httpx.AsyncClient(timeout=self.health_timeout_s) as client:
                version_resp = await client.get(f"{self.base_url}/api/version")
                if version_resp.status_code != 200:
                    return False, f"serverul Ollama a răspuns HTTP {version_resp.status_code} la /api/version"
                version = version_resp.json().get("version", "?")
                tags_resp = await client.get(f"{self.base_url}/api/tags")
                if tags_resp.status_code != 200:
                    return False, f"serverul Ollama a răspuns HTTP {tags_resp.status_code} la /api/tags"
                names = [m.get("name", "") for m in tags_resp.json().get("models", [])]
        except httpx.HTTPError as e:
            return False, f"serverul Ollama nu răspunde la {self.base_url} ({type(e).__name__})"
        except ValueError as e:
            return False, f"răspuns invalid de la serverul Ollama ({e})"

        if not any(self._model_matches(n) for n in names):
            return False, (
                f"modelul '{self.model}' nu este instalat în Ollama {version} "
                f"(rulați: ollama create {self.model} -f deploy/ollama/Modelfile)"
            )
        return True, f"ollama {version} / {self.model} instalat"

    async def assert_ready(self) -> str:
        """
        Raises LLMUnavailable when the server or the model is missing; otherwise returns the
        provenance string "ollama <version> / <model> / <quantization_level> / ctx<N>" from /api/show.
        """
        ok, reason = await self.health()
        if not ok:
            raise LLMUnavailable(f"LLM local indisponibil: {reason}")

        version = "?"
        quantization = "unknown"
        try:
            async with httpx.AsyncClient(timeout=self.health_timeout_s) as client:
                version_resp = await client.get(f"{self.base_url}/api/version")
                version = version_resp.json().get("version", "?")
                show_resp = await client.post(f"{self.base_url}/api/show", json={"model": self.model})
                if show_resp.status_code == 200:
                    quantization = show_resp.json().get("details", {}).get("quantization_level") or "unknown"
                else:
                    logger.warning(f"/api/show returned HTTP {show_resp.status_code} for '{self.model}'; provenance without quantization")
        except (httpx.HTTPError, ValueError) as e:
            raise LLMUnavailable(f"LLM local indisponibil: serverul Ollama nu răspunde la {self.base_url} ({type(e).__name__})")

        provenance = f"ollama {version} / {self.model} / {quantization} / ctx{settings.LLM_CONTEXT_TOKENS}"
        if provenance != self._logged_provenance:
            logger.info(f"Local LLM ready: {provenance}")
            self._logged_provenance = provenance
        return provenance

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int,
        seed: int,
        keep_alive: str,
    ) -> tuple[dict, dict]:
        """
        POST /api/chat with stream:false and format:<schema>. Returns (parsed_json, stats) where stats
        carries prompt_tokens, completion_tokens, seconds (wall clock) plus done_reason for diagnostics.
        """
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "keep_alive": keep_alive,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "num_ctx": settings.LLM_CONTEXT_TOKENS,
                "temperature": settings.LLM_TEMPERATURE,
                "top_k": 1,
                "seed": seed,
                "num_predict": max_tokens,
            },
        }

        started = time.perf_counter()
        resp = await self._post_chat(payload)
        seconds = time.perf_counter() - started

        try:
            data = resp.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as e:
            raise ExtractionError(f"Serverul LLM a returnat un răspuns fără conținut interpretabil: {e}")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise ExtractionError(
                f"Serverul LLM a returnat JSON invalid (done_reason={data.get('done_reason')}): {e}; conținut: {content[:300]}"
            )
        if not isinstance(parsed, dict):
            raise ExtractionError(f"Serverul LLM a returnat un JSON care nu este obiect: {content[:300]}")

        stats = {
            "prompt_tokens": int(data.get("prompt_eval_count", 0) or 0),
            "completion_tokens": int(data.get("eval_count", 0) or 0),
            "seconds": round(seconds, 3),
            "done_reason": data.get("done_reason"),
        }
        return parsed, stats

    async def _post_chat(self, payload: dict) -> httpx.Response:
        """One request with a single 2 s retry on 503 (model still loading / server busy)."""
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            except httpx.HTTPError as e:
                raise LLMUnavailable(
                    f"LLM local indisponibil: serverul Ollama nu răspunde la {self.base_url} ({type(e).__name__}: {e})"
                )

            if resp.status_code == 200:
                return resp
            if resp.status_code == 503 and attempt == 0:
                logger.warning("Ollama returned 503; retrying once in 2 s...")
                await asyncio.sleep(2.0)
                continue
            if resp.status_code == 404:
                raise LLMUnavailable(f"LLM local indisponibil: modelul '{self.model}' nu este instalat în Ollama (HTTP 404)")
            if resp.status_code == 503:
                raise LLMUnavailable(f"LLM local indisponibil: serverul Ollama a răspuns HTTP 503 de două ori la {self.base_url}")
            raise ExtractionError(f"Serverul LLM a returnat HTTP {resp.status_code}: {resp.text[:300]}")
        raise LLMUnavailable(f"LLM local indisponibil la {self.base_url}")  # unreachable, keeps the type checker honest

    async def unload(self) -> None:
        """POST /api/generate {"model", "keep_alive": 0} frees the VRAM for the next ASR run; errors are logged, never raised."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json={"model": self.model, "keep_alive": 0})
                if resp.status_code == 200:
                    logger.info(f"Local LLM '{self.model}' unloaded from VRAM")
                else:
                    logger.warning(f"Could not unload '{self.model}': HTTP {resp.status_code} {resp.text[:200]}")
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"Could not unload '{self.model}': {type(e).__name__}: {e}")


llm_client = OllamaClient(
    settings.LLM_API_BASE_URL,
    settings.LLM_MODEL_NAME,
    settings.LLM_REQUEST_TIMEOUT_S,
    settings.LLM_HEALTH_TIMEOUT_S,
)
