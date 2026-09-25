"""
Medpark Meeting Intelligence System - Core Configuration
Manages offline settings, hardware profiles, directory paths, and service configurations.
"""

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
    
    # LLM & Extraction Configuration
    LLM_PROVIDER: Literal["local_gguf", "llama_cpp_server", "mock_evaluator"] = "local_gguf"
    LLM_API_BASE_URL: str = "http://127.0.0.1:8080/v1"
    LLM_MODEL_NAME: str = "Qwen/Qwen2.5-7B-Instruct-GGUF"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096
    REQUIRE_LOCAL_LLM: bool = False  # If True, fails pipeline if local LLM server is offline
    
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
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def ensure_directories(self) -> None:
        """Create all required local directories if they do not exist."""
        for path in [self.DATA_DIR, self.UPLOADS_DIR, self.EXPORTS_DIR, self.MODELS_DIR, self.FIXTURES_DIR]:
            path.mkdir(parents=True, exist_ok=True)


# Global settings singleton
settings = Settings()
settings.ensure_directories()
