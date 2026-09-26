"""
Medpark Meeting Intelligence System - Core Configuration
Manages offline settings, hardware profiles, directory paths, and service configurations.
"""

import os
import sys
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application Metadata
    APP_NAME: str = "Medpark Offline Meeting Intelligence"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    
    # Offline & Security Policy
    OFFLINE_STRICT: bool = True
    DISABLE_TELEMETRY: bool = True
    ALLOW_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
    
    # Base Storage Directories (all local, zero cloud dependencies)
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    UPLOADS_DIR: Path = DATA_DIR / "uploads"
    EXPORTS_DIR: Path = DATA_DIR / "exports"
    MODELS_DIR: Path = DATA_DIR / "models"
    FIXTURES_DIR: Path = DATA_DIR / "fixtures"
    
    # Regional & Localization Defaults
    DEFAULT_TIMEZONE: str = "Europe/Chisinau"
    SUPPORTED_LANGUAGES: list[str] = ["ro", "ru", "en"]
    
    # Hardware & Audio Processing (RTX 3050 4GB GPU / 32GB RAM profile)
    DEFAULT_SAMPLE_RATE: int = 16000  # 16kHz mono required for speech AI
    
    # ASR Configuration (faster-whisper)
    # Options: tiny, base, small, medium, large-v3-turbo, large-v3
    WHISPER_MODEL_NAME: str = "turbo"
    WHISPER_DEVICE: Literal["cuda", "cpu", "auto"] = "auto"
    WHISPER_COMPUTE_TYPE: Literal["float16", "int8_float16", "int8"] = "int8_float16"
    WHISPER_BEAM_SIZE: int = 5
    # When the resolved device is CUDA but the runtime fails (missing cuBLAS, VRAM exhausted), a
    # silent downgrade to CPU turns a 5-minute run into an hour-long one with only a WARNING in the
    # log. Off by default so the failure is loud; set True only for machines without a usable GPU
    # where WHISPER_DEVICE cannot simply be pinned to "cpu".
    ALLOW_CPU_FALLBACK: bool = False
    
    # LLM & Extraction Configuration (Ollama native API, Qwen3-4B-Instruct Q4_K_M via deploy/ollama/Modelfile)
    # The LLM (~2.7 GB) and Whisper (~2 GB) cannot share the 4 GB VRAM: the extraction engine unloads the
    # model after each meeting so the next ASR run has the GPU to itself.
    LLM_PROVIDER: Literal["ollama", "llama_cpp_server"] = "ollama"
    LLM_API_BASE_URL: str = "http://127.0.0.1:11434"
    LLM_MODEL_NAME: str = "medpark-extractor"
    LLM_TEMPERATURE: float = 0.0
    LLM_SEED: int = 1234
    LLM_CONTEXT_TOKENS: int = 4096
    LLM_MAX_TOKENS: int = 1100
    LLM_REQUEST_TIMEOUT_S: float = 240.0
    LLM_HEALTH_TIMEOUT_S: float = 3.0
    LLM_KEEP_ALIVE: str = "10m"
    REQUIRE_LOCAL_LLM: bool = True  # If True, the pipeline fails at preflight when the local LLM is not serving
    LLM_FALLBACK_MODE: Literal["fail", "heuristic"] = "fail"  # "heuristic" only applies when REQUIRE_LOCAL_LLM is False
    # Map/reduce over the compact indexed transcript: a 60-minute meeting is ~20k tokens, far beyond one context
    LLM_CHUNK_TOKENS: int = 2300
    LLM_CHUNK_OVERLAP_TOKENS: int = 200
    LLM_CHARS_PER_TOKEN: float = 2.0
    LLM_MAX_REPAIR_ATTEMPTS: int = 1
    LLM_MAX_FAILED_CHUNK_RATIO: float = 0.20

    # SMTP Delivery Configuration (Local Mailpit by default)
    SMTP_HOST: str = "127.0.0.1"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = False
    SMTP_FROM_EMAIL: str = "minutes@medpark.md"
    SMTP_FROM_NAME: str = "Medpark Meeting Intelligence"
    ALLOW_SIMULATED_DELIVERY: bool = False  # When False, unreachable SMTP is reported as FAILED
    
    # Delivery Channel Selection (Mutual exclusivity: 'smtp' or 'n8n')
    DELIVERY_CHANNEL: Literal["smtp", "n8n"] = "smtp"
    N8N_WEBHOOK_URL: str = "http://127.0.0.1:5678/webhook/medpark-mom"
    N8N_ENABLED: bool = False  # Set True to delegate routing exclusively to n8n

    # Speaker Identity (CAM++ voiceprints, CPU-only; see docs/SPEAKER_IDENTITY_DESIGN.md)
    # Voiceprints are special-category biometric data: they live only as .npy files under VOICEPRINTS_DIR,
    # never inside a JSON store, and a name reaches a document only after a human confirms it.
    VOICE_ID_ENABLED: bool = True  # Feature flag; /ready reports it together with embedder availability
    VOICEPRINTS_DIR: Path = DATA_DIR / "voiceprints"
    SPEAKER_EMBEDDER_MODEL_PATH: Path = MODELS_DIR / "speaker" / "campplus" / "voxceleb_CAM++_LM.onnx"
    SPEAKER_CLUSTER_DISTANCE: float = 0.45  # Average-linkage cosine-distance stop; measured on real far-field audio
    SPEAKER_WINDOW_MAX_S: float = 8.0  # VAD speech regions are cut into windows of at most this many seconds
    SPEAKER_MATCH_MIN_SCORE: float = 0.50  # Below this no name is offered at all
    SPEAKER_MATCH_MIN_MARGIN: float = 0.08  # top1 - top2 must exceed this before a suggestion is made
    SPEAKER_MIN_PRINTABLE_SPEECH_S: float = 2.0  # A name prints on a segment only with at least this much speech
    SPEAKER_MIN_ENROLL_SPEECH_S: float = 20.0  # Total speech across samples required to accept an enrollment
    SPEAKER_MIN_SAMPLE_SPEECH_S: float = 4.0
    SPEAKER_MIN_COHESION: float = 0.55  # Mean pairwise cosine across a person's enrollment samples
    # There is no code path that confirms a speaker without a reviewer; the flag documents the refusal.
    ALLOW_AUTO_CONFIRM_SPEAKERS: bool = False
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def ensure_directories(self) -> None:
        """Create all required local directories if they do not exist."""
        for path in [self.DATA_DIR, self.UPLOADS_DIR, self.EXPORTS_DIR, self.MODELS_DIR, self.FIXTURES_DIR, self.VOICEPRINTS_DIR]:
            path.mkdir(parents=True, exist_ok=True)


# Global settings singleton
settings = Settings()
settings.ensure_directories()


def _bootstrap_cuda_dll_path() -> None:
    """
    Makes the pip-installed cuBLAS (nvidia-cublas-cu12) discoverable by CTranslate2 on Windows.

    CTranslate2 4.8.2 resolves cublas64_12.dll with a plain LoadLibraryA after
    SetDllDirectoryA(%CUDA_PATH%\\bin), so it honours PATH and CUDA_PATH but IGNORES
    os.add_dll_directory(). Without this, WhisperModel(device="cuda") loads fine and then fails
    at the first matrix multiply, which is how the ASR stage ended up silently on the CPU.
    Must run before the first `import ctranslate2` anywhere in the process; importing this
    module is the earliest common point.
    """
    if sys.platform != "win32":
        return
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    dll_dirs = [nvidia_root / "cublas" / "bin", nvidia_root / "cuda_nvrtc" / "bin", nvidia_root / "cuda_runtime" / "bin"]
    existing = [str(d) for d in dll_dirs if d.is_dir()]
    if not existing:
        return
    os.environ["PATH"] = os.pathsep.join(existing) + os.pathsep + os.environ.get("PATH", "")
    # CT2 appends "\bin" itself. A real CUDA toolkit's installer-set CUDA_PATH must keep precedence.
    os.environ.setdefault("CUDA_PATH", str(nvidia_root / "cublas"))


_bootstrap_cuda_dll_path()
