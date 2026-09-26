"""
Medpark Meeting Intelligence System - faster-whisper ASR Engine
Executes local multilingual speech recognition with dynamic code-switch conditioning and VRAM offloading.
"""

from pathlib import Path
import gc
import re
from typing import Optional
try:
    import ctranslate2
    from faster_whisper import WhisperModel
except ImportError:
    ctranslate2 = None
    WhisperModel = None
from app.core.config import settings
from app.core.exceptions import ASREngineError
from app.core.logging import logger
from app.models.transcript import TranscriptSegment
from app.services.asr.base import BaseASREngine
from app.services.asr.glossary import build_code_switch_prompt, MEDPARK_MEDICAL_VOCABULARY

# Vocabulary whose presence marks a segment for human verification, matched on word boundaries.
# A plain substring test flags nearly every Romanian sentence, because short acronyms such as
# "ATI" or "CT" occur inside ordinary words ("informații", "conduct").
CRITICAL_REVIEW_TERM_PATTERNS = tuple(
    (term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE))
    for term in MEDPARK_MEDICAL_VOCABULARY[:20]
)


class FasterWhisperEngine(BaseASREngine):
    """
    High-performance offline ASR engine using CTranslate2 faster-whisper.
    Optimized for Moldovan code-switched clinical recordings with transparent CPU fallback.
    """

    def __init__(self):
        self.model_name = settings.WHISPER_MODEL_NAME
        self.device = self._resolve_device()
        self.compute_type = self._resolve_compute_type()
        self._model: Optional[WhisperModel] = None

    def _resolve_device(self) -> str:
        if settings.WHISPER_DEVICE == "auto":
            has_cuda = (ctranslate2 is not None) and (ctranslate2.get_cuda_device_count() > 0)
            dev = "cuda" if has_cuda else "cpu"
            logger.info(f"Auto-detected ASR compute device: {dev.upper()}")
            return dev
        return settings.WHISPER_DEVICE

    def _resolve_compute_type(self) -> str:
        if self.device == "cuda":
            return settings.WHISPER_COMPUTE_TYPE
        return "int8"  # CPU int8 execution

    def load_model(self, force_cpu: bool = False) -> WhisperModel:
        """Loads model into memory if not already initialized."""
        if WhisperModel is None:
            raise ASREngineError("faster-whisper is not installed in this environment. Use whisper_cpp or remote ASR provider.")

        if force_cpu:
            self.device = "cpu"
            self.compute_type = "int8"
            self._model = None

        if self._model is None:
            logger.info(f"Loading faster-whisper model '{self.model_name}' on {self.device.upper()} ({self.compute_type})...")
            try:
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=str(settings.MODELS_DIR),
                    # Strict offline: the cached snapshot is the only acceptable source at inference
                    local_files_only=settings.OFFLINE_STRICT
                )
                logger.info(f"faster-whisper model initialized on {self.device.upper()}.")
            except Exception as e:
                if self.device == "cuda" and settings.ALLOW_CPU_FALLBACK:
                    logger.warning(f"CUDA initialization failed ({e}). ALLOW_CPU_FALLBACK is set: falling back to CPU int8 execution.")
                    self.device = "cpu"
                    self.compute_type = "int8"
                    self._model = WhisperModel(
                        self.model_name,
                        device="cpu",
                        compute_type="int8",
                        download_root=str(settings.MODELS_DIR),
                        local_files_only=settings.OFFLINE_STRICT
                    )
                elif self.device == "cuda":
                    raise ASREngineError(
                        f"CUDA initialization failed on device '{self.device}' ({e}). "
                        f"Refusing to degrade to CPU silently (ALLOW_CPU_FALLBACK=false); "
                        f"set WHISPER_DEVICE=cpu explicitly if this machine has no usable GPU."
                    )
                else:
                    raise ASREngineError(f"Failed to load faster-whisper model: {e}")
        return self._model

    def release_model(self) -> None:
        """Explicitly unloads model to free GPU VRAM for the downstream LLM extraction stage."""
        if self._model is not None:
            logger.info("Unloading faster-whisper from VRAM/RAM to free resources for extraction...")
            del self._model
            self._model = None
            gc.collect()

    def transcribe(
        self,
        audio_path: Path,
        initial_prompt: Optional[str] = None,
        language: Optional[str] = None
    ) -> list[TranscriptSegment]:
        """
        Transcribes audio with multilingual code-switching preservation and automatic CPU fallback.
        """
        if not audio_path.exists():
            raise ASREngineError(f"Audio file does not exist: {audio_path}")

        prompt = initial_prompt or build_code_switch_prompt()
        logger.info(f"Starting ASR transcription on {audio_path.name} with multilingual prompt conditioning...")

        # cuBLAS is loaded lazily at the first matrix multiply, so a CUDA runtime failure surfaces
        # HERE rather than at model load. It is only downgraded to CPU when explicitly allowed.
        try:
            return self._run_transcription(audio_path, prompt, language)
        except Exception as e:
            err_str = str(e)
            cuda_runtime_failure = self.device == "cuda" and (
                "cublas" in err_str.lower() or "cuda" in err_str.lower() or "dll" in err_str.lower()
            )
            if cuda_runtime_failure and not settings.ALLOW_CPU_FALLBACK:
                logger.error(f"CUDA runtime failure during transcription: {err_str}")
                raise ASREngineError(
                    f"CUDA runtime failure during ASR ({err_str}). Refusing to degrade to CPU silently "
                    f"(ALLOW_CPU_FALLBACK=false): a CPU run is ~4x over the time budget and must be a deliberate choice."
                )
            if cuda_runtime_failure:
                logger.warning(f"CUDA runtime failure ({err_str}). ALLOW_CPU_FALLBACK is set: falling back to CPU int8...")
                self.release_model()
                # A failing fallback must surface as ASREngineError like any other ASR failure,
                # instead of leaking a raw CTranslate2 exception to the pipeline and the API.
                try:
                    self.load_model(force_cpu=True)
                    return self._run_transcription(audio_path, prompt, language)
                except Exception as fallback_error:
                    logger.error(f"CPU fallback transcription also failed: {fallback_error}")
                    raise ASREngineError(f"ASR transcription failed after CPU fallback: {fallback_error}")
            else:
                logger.error(f"Error during speech transcription: {e}")
                raise ASREngineError(f"ASR transcription failed: {e}")

    def _run_transcription(
        self,
        audio_path: Path,
        prompt: str,
        language: Optional[str]
    ) -> list[TranscriptSegment]:
        model = self.load_model()
        segments_gen, info = model.transcribe(
            str(audio_path),
            beam_size=settings.WHISPER_BEAM_SIZE,
            language=language,
            initial_prompt=prompt,
            # The conditioning prompt must not become decoder context for the next window:
            # with carry-over enabled Whisper loops on the glossary and emits it back as if it
            # had been spoken, which is exactly the hallucination the evidence grounding forbids.
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=False
        )

        detected_primary = info.language
        prob = info.language_probability
        logger.info(f"Primary detected audio language: {detected_primary} (prob: {prob:.2f})")

        results: list[TranscriptSegment] = []
        for seg in segments_gen:
            text = seg.text.strip()
            if not text:
                continue

            is_flagged, reason = self._check_review_flags(text, seg.avg_logprob)

            segment_obj = TranscriptSegment(
                start=round(seg.start, 2),
                end=round(seg.end, 2),
                speaker="Speaker 1",
                raw_text=text,
                language=detected_primary,
                confidence=round(min(1.0, max(0.0, 1.0 + (seg.avg_logprob / 5.0))), 2),
                is_flagged=is_flagged,
                flag_reason=reason
            )
            results.append(segment_obj)

        if not results:
            logger.info("No intelligible speech detected in audio file.")

        logger.info(f"Transcription complete: extracted {len(results)} segments.")
        return results

    def _check_review_flags(self, text: str, avg_logprob: float) -> tuple[bool, Optional[str]]:
        if avg_logprob < -1.1:
            return True, "Low acoustic confidence / unclear speech"
        
        words = text.split()
        for w in words:
            if any(char.isdigit() for char in w):
                return True, "Contains numerical values/dates requiring verification"

        for term, pattern in CRITICAL_REVIEW_TERM_PATTERNS:
            if pattern.search(text):
                return True, f"Contains critical medical term: '{term}'"

        return False, None


whisper_engine = FasterWhisperEngine()
