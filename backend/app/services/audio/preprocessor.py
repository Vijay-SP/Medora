"""
Medpark Meeting Intelligence System - Audio Preprocessor
Normalizes arbitrary audio streams (WAV, MP3, M4A, WebM) to 16kHz mono WAV for high-fidelity ASR.
"""

import os
import shutil
import subprocess
from pathlib import Path
import soundfile as sf
from app.core.config import settings
from app.core.exceptions import AudioProcessingError
from app.core.logging import logger


class AudioPreprocessor:
    """Prepares and normalizes meeting audio for speech recognition."""

    def __init__(self, target_sample_rate: int = settings.DEFAULT_SAMPLE_RATE):
        self.target_sample_rate = target_sample_rate
        self.ffmpeg_bin = self._find_ffmpeg_binary()
        self.ffprobe_bin = self._find_ffprobe_binary()

    def _find_ffmpeg_binary(self) -> str:
        """Finds ffmpeg in PATH or common Windows package directories."""
        found = shutil.which("ffmpeg")
        if found:
            return found
        
        # Check WinGet package location on Windows
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            winget_path = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            if winget_path.exists():
                for p in winget_path.glob("**/ffmpeg.exe"):
                    return str(p)

        return "ffmpeg"

    def _find_ffprobe_binary(self) -> str:
        """Finds ffprobe in PATH or common Windows package directories."""
        found = shutil.which("ffprobe")
        if found:
            return found
        
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            winget_path = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            if winget_path.exists():
                for p in winget_path.glob("**/ffprobe.exe"):
                    return str(p)

        return "ffprobe"

    def inspect_audio(self, audio_path: Path) -> dict:
        """Inspects audio file properties (duration, sample rate, channels)."""
        try:
            info = sf.info(str(audio_path))
            return {
                "duration_seconds": info.duration,
                "sample_rate": info.samplerate,
                "channels": info.channels,
                "format": info.format,
                "subtype": info.subtype
            }
        except Exception:
            return self._inspect_with_ffprobe(audio_path)

    def _inspect_with_ffprobe(self, audio_path: Path) -> dict:
        cmd = [
            self.ffprobe_bin, "-v", "error",
            "-show_entries", "format=duration:stream=sample_rate,channels",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            lines = res.stdout.strip().split()
            sample_rate = int(lines[0]) if len(lines) > 0 else 16000
            channels = int(lines[1]) if len(lines) > 1 else 1
            duration = float(lines[2]) if len(lines) > 2 else 0.0
            return {
                "duration_seconds": duration,
                "sample_rate": sample_rate,
                "channels": channels,
                "format": audio_path.suffix.lstrip(".").upper(),
                "subtype": "UNKNOWN"
            }
        except Exception as ex:
            logger.warning(f"Could not inspect audio with ffprobe: {ex}")
            return {"duration_seconds": 0.0, "sample_rate": 16000, "channels": 1, "format": "UNKNOWN", "subtype": "UNKNOWN"}

    def normalize(self, source_audio_path: Path, output_wav_path: Path) -> tuple[Path, float]:
        """
        Converts input audio to standard 16,000 Hz, 16-bit mono PCM WAV.
        Preserves original timeline exactly.
        """
        if not source_audio_path.exists():
            raise AudioProcessingError(f"Source audio file not found: {source_audio_path}")

        output_wav_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.ffmpeg_bin, "-y",
            "-i", str(source_audio_path),
            "-ar", str(self.target_sample_rate),
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_wav_path)
        ]

        logger.info(f"Normalizing audio: {source_audio_path.name} -> {output_wav_path.name}")
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise AudioProcessingError(f"FFmpeg normalization failed: {res.stderr}")
        except FileNotFoundError:
            raise AudioProcessingError("FFmpeg executable not found on system PATH. Please verify installation.")

        # Validate normalized output
        info = self.inspect_audio(output_wav_path)
        duration = info.get("duration_seconds", 0.0)
        logger.info(f"Audio normalized successfully. Duration: {duration:.2f}s, Rate: {self.target_sample_rate}Hz")
        return output_wav_path, duration


audio_preprocessor = AudioPreprocessor()
