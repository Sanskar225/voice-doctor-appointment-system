"""Typed application configuration loaded once at startup."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    """Single source of truth for runtime configuration."""

    app_name: str = "Aurelia Health Voice Desk"
    app_version: str = "2.1.0"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Persistence
    db_path: Path = Field(default_factory=lambda: BACKEND_ROOT / "clinic.db")
    sqlite_busy_timeout_ms: int = 5000

    # Voice pipeline & providers
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "EXAVITQu4vr4xnSDxMaL"  # Sarah (premade free-tier compatible)
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    elevenlabs_stt_mode: Literal["realtime", "segmented"] = "realtime"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_use_vertex: bool = False

    # Audio & session guardrails
    audio_sample_rate: int = 16000
    max_concurrent_calls: int = 10
    call_session_timeout_secs: int = 600
    tool_timeout_secs: float = 10.0
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    @property
    def missing_voice_keys(self) -> list[str]:
        missing: list[str] = []
        if not self.elevenlabs_api_key:
            missing.append("ELEVENLABS_API_KEY")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        return missing

    @property
    def voice_ready(self) -> bool:
        return len(self.missing_voice_keys) == 0


def load_settings(*, db_path: Path | None = None) -> Settings:
    """Load environment files and construct a validated Settings instance."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(BACKEND_ROOT / ".env", override=False)

    cors_raw = os.getenv("CORS_ORIGINS", "").strip()
    cors_origins = (
        [origin.strip() for origin in cors_raw.split(",") if origin.strip()]
        if cors_raw
        else [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    stt_mode_raw = os.getenv("ELEVENLABS_STT_MODE", "realtime").strip().lower()
    stt_mode: Literal["realtime", "segmented"] = (
        "segmented" if stt_mode_raw == "segmented" else "realtime"
    )

    return Settings(
        host=os.getenv("HOST", "0.0.0.0").strip(),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        db_path=db_path or Path(os.getenv("CLINIC_DB_PATH", str(BACKEND_ROOT / "clinic.db"))),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL").strip(),
        elevenlabs_tts_model=os.getenv("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5").strip(),
        elevenlabs_stt_mode=stt_mode,
        gemini_api_key=(
            os.getenv("GEMINI_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        ),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip(),
        gemini_use_vertex=os.getenv("GEMINI_USE_VERTEX", "false").strip().lower()
        in ("1", "true", "yes"),
        max_concurrent_calls=int(os.getenv("MAX_CONCURRENT_CALLS", "10")),
        call_session_timeout_secs=int(os.getenv("CALL_SESSION_TIMEOUT_SECS", "600")),
        cors_origins=cors_origins,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
