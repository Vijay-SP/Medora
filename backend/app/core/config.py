"""
Medpark Meeting Intelligence System - Core Configuration
Manages offline settings, hardware profiles, directory paths, and service configurations.
"""

import os
import sys
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
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
    OUTBOX_DIR: Path | None = None
    UPLOADS_DIR: Path = DATA_DIR / "uploads"
    EXPORTS_DIR: Path = DATA_DIR / "exports"
    MODELS_DIR: Path = DATA_DIR / "models"
    FIXTURES_DIR: Path = DATA_DIR / "fixtures"
    ADAPTATION_DIR: Path | None = None

    # ASR Learning & Adaptation
    ASR_LEARNING_ENABLED: bool = False
    ASR_DYNAMIC_CONTEXT_ENABLED: bool = False
    
    # Regional & Localization Defaults
    DEFAULT_TIMEZONE: str = "Europe/Chisinau"
    SUPPORTED_LANGUAGES: list[str] = ["ro", "ru", "en"]
    
    # Hardware & Audio Processing (RTX 3050 4GB GPU / 32GB RAM profile)
    DEFAULT_SAMPLE_RATE: int = 16000  # 16kHz mono required for speech AI
    
    # ASR Configuration
    # Provider options: 'faster_whisper' (default for CUDA/CPU servers), 'whisper_cpp' (Mac Metal/CPU), 'remote' (LAN client)
    ASR_PROVIDER: Literal["faster_whisper", "whisper_cpp", "remote"] = "faster_whisper"

    # Remote ASR Configuration (for teammates connecting over LAN)
    REMOTE_ASR_BASE_URL: str = "http://127.0.0.1:8001"
    REMOTE_ASR_API_KEY: str = ""
    REMOTE_ASR_TIMEOUT_S: float = 3600.0
    REMOTE_ASR_POLL_INTERVAL_S: float = 2.0

    # whisper.cpp ASR Configuration (local Metal on Apple Silicon / CPU)
    WHISPER_CPP_BINARY: Path = Path("/opt/homebrew/bin/whisper-cli")
    WHISPER_CPP_MODEL: Path = Path("data/models/whisper.cpp/ggml-large-v3-q5_0.bin")
    WHISPER_CPP_VAD_MODEL: Path = Path("data/models/whisper.cpp/ggml-silero-v6.2.0.bin")
    WHISPER_CPP_THREADS: int = 4
    WHISPER_CPP_USE_GPU: bool = True
    WHISPER_CPP_TIMEOUT_S: int = 1800

    # faster-whisper Configuration (Options: tiny, base, small, medium, large-v3-turbo, large-v3)
    WHISPER_MODEL_NAME: str = "turbo"
    WHISPER_DEVICE: Literal["cuda", "cpu", "auto"] = "auto"
    WHISPER_COMPUTE_TYPE: Literal["float16", "int8_float16", "int8"] = "int8_float16"
    WHISPER_BEAM_SIZE: int = 5
    # When the resolved device is CUDA but the runtime fails (missing cuBLAS, VRAM exhausted), a
    # silent downgrade to CPU turns a 5-minute run into an hour-long one with only a WARNING in the
    # log. Off by default so the failure is loud; set True only for machines without a usable GPU
    # where WHISPER_DEVICE cannot simply be pinned to "cpu".
    ALLOW_CPU_FALLBACK: bool = False
    # Code-switching ASR (docs/ASR_CODE_SWITCHING.md). A single whole-file pass detects ONE language from the
    # first 30 s and stamps it on every segment, so Romanian speech in a Russian-opened meeting comes out as
    # Cyrillic nonsense. Instead the file is cut into VAD-packed windows and each window gets its own
    # language identification restricted to WHISPER_LANGUAGES (unrestricted LID may pick "en" and make
    # Whisper TRANSLATE the speech). "batched" only switches the decode path; the restriction is the same.
    WHISPER_STRATEGY: Literal["windowed", "batched"] = "windowed"
    WHISPER_LANGUAGES: list[str] = ["ro", "ru", "en"]
    WHISPER_BATCH_SIZE: int = 4  # Batching costs VRAM; 4 is the margin left next to turbo on a 4 GB card
    WHISPER_CHUNK_LENGTH_S: int = 12
    # Window packing: hard cuts at VAD silences, no overlap. Windows below MIN merge into the previous one;
    # windows under ~4 s carry no usable LID signal and inherit their neighbour's language.
    ASR_WINDOW_MIN_S: float = 1.5
    ASR_WINDOW_TARGET_S: float = 12.0
    ASR_WINDOW_MAX_S: float = 20.0
    ASR_WINDOW_HARD_CAP_S: float = 28.0  # Whisper's encoder consumes 30 s; never exceed it
    # Windows whose top restricted-LID probability is below this get a second decode in the runner-up
    # language and keep the better avg_logprob (never rescore everything: it doubles the cost).
    ASR_LID_RESCORE_BELOW: float = 0.70
    ASR_HOTWORDS_ENABLED: bool = True  # Per-language clinical hotwords (<= 80 tokens) instead of an initial_prompt
    ASR_LEXICON_ENABLED: bool = True  # Post-decode clinical lexicon corrections (recorded in segment.corrections)
    # Post-decode garbage filter: segments beyond any of these are KEPT but flagged "low_confidence_asr".
    ASR_GARBAGE_LOGPROB: float = -1.5
    ASR_GARBAGE_COMPRESSION: float = 2.4
    ASR_GARBAGE_NO_SPEECH: float = 0.85

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
    # Synthesis writes three summaries (RO/RU/EN) in one call and translation re-emits every item: both need more
    # room than a map call. Each call is still clamped so that prompt + num_predict fits LLM_CONTEXT_TOKENS.
    LLM_SYNTHESIS_MAX_TOKENS: int = 1800
    LLM_TRANSLATION_MAX_TOKENS: int = 1800
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

    # SMTP Delivery: Configure client/hospital server (host, port, auth) and update FROM sender info
    SMTP_HOST: str = "127.0.0.1"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = False
    SMTP_STARTTLS: bool | None = None
    SMTP_FROM_EMAIL: str = "minutes@medpark.md"
    SMTP_FROM_NAME: str = "Medpark Meeting Intelligence"
    ALLOW_SIMULATED_DELIVERY: bool = False
    ENABLE_LOCAL_OUTBOX_FALLBACK: bool = True
    SMTP_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0, le=60)
    
    # Delivery Routing: 'smtp', 'n8n', or 'local_outbox'
    DELIVERY_CHANNEL: Literal["smtp", "n8n", "local_outbox"] = "smtp"
    N8N_WEBHOOK_URL: str = "http://127.0.0.1:5678/webhook/medpark-mom"
    N8N_ENABLED: bool = False

    # Speaker Identity (CAM++ voiceprints, CPU-only; see docs/SPEAKER_IDENTITY_DESIGN.md)
    # Voiceprints are special-category biometric data: they live only as .npy files under VOICEPRINTS_DIR,
    # never inside a JSON store, and a name reaches a document only after a human confirms it.
    VOICE_ID_ENABLED: bool = True  # Feature flag; /ready reports it together with embedder availability
    VOICEPRINTS_DIR: Path = DATA_DIR / "voiceprints"
    SPEAKER_EMBEDDER_MODEL_PATH: Path = MODELS_DIR / "speaker" / "campplus" / "voxceleb_CAM++_LM.onnx"
    SPEAKER_CLUSTER_DISTANCE: float = 0.45  # Average-linkage cosine-distance stop; measured on real far-field audio
    SPEAKER_MAX_CLUSTERS: int = 5  # Max speaker clusters cap for 5-person meetings
    SPEAKER_WINDOW_MAX_S: float = 8.0  # VAD speech regions are cut into windows of at most this many seconds
    SPEAKER_MATCH_MIN_SCORE: float = 0.50  # Below this no name is offered at all
    SPEAKER_MATCH_MIN_MARGIN: float = 0.08  # top1 - top2 must exceed this before a suggestion is made
    SPEAKER_MIN_PRINTABLE_SPEECH_S: float = 2.0  # A name prints on a segment only with at least this much speech
    SPEAKER_MIN_ENROLL_SPEECH_S: float = 20.0  # Total speech across samples required to accept an enrollment
    SPEAKER_MIN_SAMPLE_SPEECH_S: float = 4.0
    SPEAKER_MIN_COHESION: float = 0.55  # Mean pairwise cosine across a person's enrollment samples
    # Direct speaker attribution from high-confidence voiceprint matches
    ALLOW_AUTO_CONFIRM_SPEAKERS: bool = False
    SPEAKER_AUTO_CONFIRM_MIN_SCORE: float = 0.70  # Min fused similarity to auto-attribute
    SPEAKER_AUTO_CONFIRM_MIN_MARGIN: float = 0.08  # Min margin over runner-up
    SPEAKER_AUTO_CONFIRM_MIN_VOTE_RATIO: float = 0.60  # Min segment voting consensus
    SPEAKER_BOUNDARY_REFINE_ENABLED: bool = True
    
    model_config = SettingsConfigDict(
        env_file=(
            Path(__file__).resolve().parent.parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent.parent / ".env",
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @model_validator(mode="after")
    def resolve_outbox_directory(self):
        if self.OUTBOX_DIR is None:
            self.OUTBOX_DIR = self.DATA_DIR / "outbox"
        return self

    @model_validator(mode="after")
    def resolve_adaptation_directory(self):
        if self.ADAPTATION_DIR is None:
            self.ADAPTATION_DIR = self.DATA_DIR / "adaptation"
        return self

    @model_validator(mode="after")
    def resolve_smtp_tls_defaults(self):
        if self.SMTP_USE_TLS:
            self.SMTP_STARTTLS = False
        elif self.SMTP_PORT == 1025 and self.SMTP_HOST in ("127.0.0.1", "localhost", "::1"):
            if self.SMTP_STARTTLS is None:
                self.SMTP_STARTTLS = False
        return self

    def ensure_directories(self) -> None:
        """Create all required local directories if they do not exist."""
        dirs = [self.DATA_DIR, self.UPLOADS_DIR, self.EXPORTS_DIR, self.MODELS_DIR, self.FIXTURES_DIR, self.VOICEPRINTS_DIR, self.OUTBOX_DIR]
        if self.ADAPTATION_DIR:
            dirs.append(self.ADAPTATION_DIR)
        for path in dirs:
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
