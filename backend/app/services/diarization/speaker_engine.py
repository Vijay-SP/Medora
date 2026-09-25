"""
Medpark Meeting Intelligence System - Acoustic Speaker Diarization Engine
Provides fast, offline speaker turn clustering and attendee mapping without external token gates.
"""

from pathlib import Path
from typing import Optional
import numpy as np
import soundfile as sf
from app.core.logging import logger
from app.models.meeting import Attendee
from app.models.transcript import TranscriptSegment
from app.services.diarization.base import BaseDiarizationEngine


class AcousticDiarizer(BaseDiarizationEngine):
    """
    Lightweight, deterministic acoustic diarizer designed for offline hospital environments.
    Extracts spectral energy, zero-crossing, and harmonic profiles to cluster speaker turns
    without incurring high-latency deep learning overhead on laptop hardware.
    """

    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
        attendees: Optional[list[Attendee]] = None
    ) -> list[TranscriptSegment]:
        if not segments:
            return []

        try:
            data, sr = sf.read(str(audio_path))
            if data.ndim > 1:
                data = data.mean(axis=1)
        except Exception as e:
            logger.warning(f"Could not read audio for acoustic diarization: {e}. Keeping default speaker labels.")
            return segments

        logger.info(f"Extracting acoustic fingerprints for {len(segments)} segments...")

        features = []
        for seg in segments:
            s_idx = max(0, int(seg.start * sr))
            e_idx = min(len(data), int(seg.end * sr))
            chunk = data[s_idx:e_idx]

            if len(chunk) < sr * 0.2:
                # Very short chunk, default to zero vector
                features.append(np.zeros(4))
                continue

            # Feature 1: RMS Energy
            rms = np.sqrt(np.mean(chunk ** 2) + 1e-9)
            # Feature 2: Zero Crossing Rate
            zcr = np.mean(np.abs(np.diff(np.sign(chunk)))) / 2.0
            # Feature 3: Spectral Centroid approximation
            fft_mag = np.abs(np.fft.rfft(chunk[:1024]))
            freqs = np.fft.rfftfreq(len(chunk[:1024]), 1.0 / sr)
            spectral_centroid = np.sum(freqs * fft_mag) / (np.sum(fft_mag) + 1e-9) / (sr / 2.0)
            # Feature 4: Peak-to-average ratio
            crest = np.max(np.abs(chunk)) / (rms + 1e-9)

            feat = np.array([rms, zcr, spectral_centroid, crest])
            features.append(feat)

        feat_matrix = np.array(features)
        
        # Determine number of clusters
        num_clusters = min(4, max(2, len(attendees))) if attendees else 3
        if len(segments) < num_clusters:
            num_clusters = max(1, len(segments))

        # Standardize features
        norm = np.linalg.norm(feat_matrix, axis=1, keepdims=True) + 1e-9
        feat_normalized = feat_matrix / norm

        # Simple K-Means clustering
        np.random.seed(42)
        initial_indices = np.random.choice(len(feat_normalized), size=num_clusters, replace=False)
        centroids = feat_normalized[initial_indices]

        labels = np.zeros(len(feat_normalized), dtype=int)
        for _ in range(10):
            # Compute cosine similarities to centroids
            sims = np.dot(feat_normalized, centroids.T)
            new_labels = np.argmax(sims, axis=1)
            if np.array_equal(labels, new_labels):
                break
            labels = new_labels
            for k in range(num_clusters):
                mask = labels == k
                if np.any(mask):
                    new_c = np.mean(feat_normalized[mask], axis=0)
                    centroids[k] = new_c / (np.linalg.norm(new_c) + 1e-9)

        # Anonymous speaker labeling by cluster without guessing attendee identities
        speaker_mapping: dict[int, str] = {k: f"Speaker {k + 1}" for k in range(num_clusters)}

        # Assign to segments
        updated_segments: list[TranscriptSegment] = []
        for i, seg in enumerate(segments):
            cluster_id = int(labels[i])
            seg.speaker = speaker_mapping.get(cluster_id, f"Speaker {cluster_id + 1}")
            seg.speaker_id = None
            
            # Contextual identity suggestion (only if participant name is explicitly spoken)
            suggested = None
            if attendees:
                lower_text = seg.display_text.lower()
                for att in attendees:
                    # Check if attendee's surname or first name is referenced in utterance
                    name_parts = att.name.lower().split()
                    if any(len(p) > 3 and p in lower_text for p in name_parts):
                        suggested = att.name
                        break
            seg.suggested_identity = suggested
            updated_segments.append(seg)

        logger.info(f"Diarization clustered {len(segments)} segments into {num_clusters} anonymous speaker turns.")
        return updated_segments


diarization_engine = AcousticDiarizer()
