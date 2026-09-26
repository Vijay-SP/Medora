"""
Medpark Meeting Intelligence System - Speaker Embedding (WeSpeaker CAM++ via onnxruntime, CPU)

Wraps data/models/speaker/campplus/voxceleb_CAM++_LM.onnx (input "feats" [B, T, 80] float32, output "embs"
[B, 512]). Features MUST come from app.services.diarization.fbank.kaldi_fbank with CMN; see that module's
docstring and data/models/speaker/campplus/MODEL_CARD.md. The session is created lazily on first use and the
module never raises at import time, so the rest of the application starts even when the weights are missing.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.logging import logger
from app.services.diarization.fbank import INT16_SCALE, kaldi_fbank

MODEL_RELATIVE_PATH = Path("speaker") / "campplus" / "voxceleb_CAM++_LM.onnx"
EXPECTED_SAMPLE_RATE = 16000
NUM_MEL_BINS = 80
# Below this the TSTP pooling has almost nothing to average; 0.3 s = 28 frames.
MIN_SECONDS = 0.3
MAX_BATCH = 32
# Embedding-space identity: a voiceprint is only comparable with embeddings from the same model file,
# the same output dimension and the same pooling recipe ("p1" = one forward pass over the pooled speech,
# L2 after mean). Bump the recipe suffix if the pooling ever changes; the sha256 prefix follows the file.
SPACE_MODEL_NAME = "campplus-LM"
SPACE_POOLING_RECIPE = "p1"


def _default_model_path() -> Path:
    try:
        from app.core.config import settings  # local import: settings creates directories on import

        configured = getattr(settings, "SPEAKER_EMBEDDER_MODEL_PATH", None)
        if configured:
            return Path(configured)
        return Path(settings.MODELS_DIR) / MODEL_RELATIVE_PATH
    except Exception:  # pragma: no cover - only when settings cannot be constructed
        return Path(__file__).resolve().parents[4] / "data" / "models" / MODEL_RELATIVE_PATH


def build_space_id(model_sha256: str, dim: int) -> str:
    """Space identifier for a model file digest and embedding size, e.g. 'campplus-LM@1068e4ac3a76/d512/p1'."""
    return f"{SPACE_MODEL_NAME}@{model_sha256[:12]}/d{int(dim)}/{SPACE_POOLING_RECIPE}"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors (safe for zero vectors: returns 0.0)."""
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class SpeakerEmbedder:
    """
    CPU-only speaker embedding extractor. Thread-safe lazy initialisation; one INFO log line on first load.

    embed()/embed_batch() return L2-normalised float32 embeddings so cosine similarity is a plain dot product.
    """

    def __init__(self, model_path: Optional[Path] = None, threads: int = 4):
        self.model_path = Path(model_path) if model_path is not None else _default_model_path()
        self.threads = int(threads)
        self._session = None
        self._input_name: Optional[str] = None
        self._output_name: Optional[str] = None
        self._dim: Optional[int] = None
        self._load_error: Optional[str] = None
        self._model_sha256: Optional[str] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loading
    def _load(self):
        if self._session is not None:
            return self._session
        with self._lock:
            if self._session is not None:
                return self._session
            if self._load_error is not None:
                return None
            if not self.model_path.is_file():
                self._load_error = f"speaker embedding model not found: {self.model_path}"
                logger.warning(self._load_error)
                return None
            try:
                import onnxruntime as ort

                opts = ort.SessionOptions()
                opts.intra_op_num_threads = self.threads
                opts.inter_op_num_threads = 1
                session = ort.InferenceSession(str(self.model_path), opts, providers=["CPUExecutionProvider"])
                inputs = session.get_inputs()
                outputs = session.get_outputs()
                if len(inputs) != 1 or len(outputs) != 1:
                    raise RuntimeError(f"expected 1 input / 1 output, got {len(inputs)} / {len(outputs)}")
                in_shape = inputs[0].shape
                if len(in_shape) != 3 or in_shape[2] != NUM_MEL_BINS:
                    raise RuntimeError(f"unexpected input shape {in_shape}; expected [B, T, {NUM_MEL_BINS}]")
                out_shape = outputs[0].shape
                dim = out_shape[-1]
                if not isinstance(dim, int):
                    # dynamic output dim: resolve it with one tiny forward pass
                    probe = session.run(None, {inputs[0].name: np.zeros((1, 50, NUM_MEL_BINS), np.float32)})[0]
                    dim = int(probe.shape[-1])
                self._input_name = inputs[0].name
                self._output_name = outputs[0].name
                self._dim = int(dim)
                self._session = session
                logger.info(
                    f"Speaker embedder loaded: {self.model_path.name} (input={self._input_name}{in_shape}, "
                    f"output={self._output_name}{out_shape}, dim={self._dim}, threads={self.threads}, CPU)"
                )
            except Exception as exc:
                self._load_error = f"speaker embedding model failed to load ({self.model_path}): {exc}"
                logger.warning(self._load_error)
                return None
        return self._session

    @property
    def available(self) -> bool:
        """True when the ONNX file exists and the session loads (loads on first call)."""
        return self._load() is not None

    @property
    def dim(self) -> int:
        session = self._load()
        if session is None:
            raise RuntimeError(self._load_error or "speaker embedder unavailable")
        return int(self._dim)  # type: ignore[arg-type]

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    @property
    def model_sha256(self) -> Optional[str]:
        """sha256 of the ONNX file (computed once, lazily); None when the file is missing."""
        if self._model_sha256 is None and self.model_path.is_file():
            hasher = hashlib.sha256()
            with open(self.model_path, "rb") as fp:
                while chunk := fp.read(1 << 20):
                    hasher.update(chunk)
            self._model_sha256 = hasher.hexdigest()
        return self._model_sha256

    @property
    def space_id(self) -> Optional[str]:
        """
        Identity of the embedding space every voiceprint and cached embedding is bound to
        ('campplus-LM@<sha256[:12]>/d512/p1'). None when the embedder is unavailable: nothing may be
        scored or enrolled against an undefined space.
        """
        if not self.available:
            return None
        digest = self.model_sha256
        if digest is None:
            return None
        return build_space_id(digest, self.dim)

    # ------------------------------------------------------------------ features
    @staticmethod
    def features(waveform: np.ndarray, sample_rate: int = EXPECTED_SAMPLE_RATE) -> np.ndarray:
        """(T, 80) CMN'd Kaldi fbank for one waveform. Refuses non-16 kHz input instead of guessing."""
        if sample_rate != EXPECTED_SAMPLE_RATE:
            raise ValueError(f"speaker embedder expects {EXPECTED_SAMPLE_RATE} Hz audio, got {sample_rate}")
        x = np.asarray(waveform)
        if x.ndim == 2:
            x = x.mean(axis=1)
        if np.issubdtype(x.dtype, np.integer):
            # PCM16 samples (soundfile dtype="int16", wave module): bring them to [-1, 1] here so the
            # x32768 inside kaldi_fbank is applied exactly once rather than twice.
            x = x.astype(np.float32) / np.float32(INT16_SCALE)
        if len(x) < int(MIN_SECONDS * sample_rate):
            raise ValueError(f"audio too short for a speaker embedding: {len(x) / sample_rate:.3f}s < {MIN_SECONDS}s")
        return kaldi_fbank(x, sample_rate=sample_rate, num_mel_bins=NUM_MEL_BINS, window="hamming", dither=0.0, cmn=True)

    # ------------------------------------------------------------------ inference
    def _run(self, feats: np.ndarray) -> np.ndarray:
        session = self._load()
        if session is None:
            raise RuntimeError(self._load_error or "speaker embedder unavailable")
        out = session.run([self._output_name], {self._input_name: feats.astype(np.float32, copy=False)})[0]
        out = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms < 1e-12, 1.0, norms)

    def embed(self, waveform: np.ndarray, sample_rate: int = EXPECTED_SAMPLE_RATE) -> np.ndarray:
        """L2-normalised (dim,) float32 embedding of one waveform."""
        feats = self.features(waveform, sample_rate)
        return self._run(feats[None, :, :])[0]

    def embed_batch(self, waveforms: list[np.ndarray], sample_rate: int = EXPECTED_SAMPLE_RATE) -> np.ndarray:
        """
        (n, dim) L2-normalised embeddings, rows aligned with the input list.

        Waveforms are bucketed by exact frame count and each bucket is run as one batch (at most MAX_BATCH
        rows). Buckets rather than zero-padding: padding CMN'd features with zeros (or with silence, which
        after CMN is not zero) changes the statistics pooling and therefore the embedding, so results would
        differ from embed(). Fixed-size sliding windows all land in one bucket and get full batching.
        """
        if not waveforms:
            return np.zeros((0, self.dim), dtype=np.float32)
        feats = [self.features(w, sample_rate) for w in waveforms]
        result = np.zeros((len(feats), self.dim), dtype=np.float32)
        buckets: dict[int, list[int]] = {}
        for i, f in enumerate(feats):
            buckets.setdefault(f.shape[0], []).append(i)
        for _, indices in sorted(buckets.items()):
            for start in range(0, len(indices), MAX_BATCH):
                chunk = indices[start:start + MAX_BATCH]
                batch = np.stack([feats[i] for i in chunk], axis=0)
                result[chunk] = self._run(batch)
        return result


speaker_embedder = SpeakerEmbedder()
