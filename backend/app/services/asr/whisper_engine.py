"""
Medpark Meeting Intelligence System - faster-whisper ASR Engine
Executes local code-switched speech recognition (Romanian / Russian / English) with per-window
restricted language identification and VRAM offloading.

Why per window (docs/ASR_CODE_SWITCHING.md): faster-whisper's whole-file pass detects ONE language
from the first 30 s and stamps it on every segment; on the real recording all segments came out "ru"
and Romanian clinical speech was rendered as Cyrillic nonsense. Here the file is cut at VAD silences
into ~12 s windows; each window is encoded once, its language is chosen among WHISPER_LANGUAGES from
that same encoder output, and it is decoded with the language token forced. Unrestricted LID
(`multilingual=True`) is never used: it picked "en" on Romanian speech and Whisper TRANSLATED it.

Two strategies share the same post-processing:
  windowed  - sequential: one encoder pass + one decode per window (temperature fallback available);
  batched   - MedparkBatchedPipeline decodes WHISPER_BATCH_SIZE windows per forward pass.
"""

from dataclasses import dataclass, field
from pathlib import Path
import gc
import re
import time
from typing import Any, Optional

import numpy as np

try:
    import ctranslate2
    from faster_whisper import BatchedInferencePipeline, WhisperModel
    from faster_whisper.audio import decode_audio, pad_or_trim
    from faster_whisper.tokenizer import Tokenizer
    from faster_whisper.transcribe import Segment, TranscriptionOptions, get_suppressed_tokens
except ImportError:
    ctranslate2 = None
    BatchedInferencePipeline = None
    WhisperModel = None
    decode_audio = None
    pad_or_trim = None
    Tokenizer = None
    Segment = None
    TranscriptionOptions = None
    get_suppressed_tokens = None
from app.core.config import settings
from app.core.exceptions import ASREngineError
from app.core.logging import logger
from app.models.transcript import TranscriptSegment
from app.services.asr.base import BaseASREngine
from app.services.asr.glossary import MEDPARK_MEDICAL_VOCABULARY, hotwords_for
from app.services.asr.lexicon import correct_segment
from app.services.asr.text_lid import TextLID, detect_text_language, language_spans
from app.services.asr.windowing import SAMPLE_RATE, DecodeWindow, pack_windows, speech_regions

# Vocabulary whose presence marks a segment for human verification, matched on word boundaries.
# A plain substring test flags nearly every Romanian sentence, because short acronyms such as
# "ATI" or "CT" occur inside ordinary words ("informații", "conduct").
CRITICAL_REVIEW_TERM_PATTERNS = tuple(
    (term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE))
    for term in MEDPARK_MEDICAL_VOCABULARY[:20]
)

# Decoder options, each chosen against a verified pathology of the previous whole-file pass:
#   word_timestamps=True        boundaries from DTW word alignment instead of timestamp tokens (integer-second
#                               durations and zero gaps came from word_timestamps=False), and it is the
#                               precondition for hallucination_silence_threshold to do anything at all;
#   condition_on_previous_text  False: the previous window's text must not become decoder context;
#   initial_prompt=None         the 257-token prompt overflowed the 223-token slot and was continued as speech;
#   repetition_penalty 1.1 / no_repeat_ngram_size 4 / compression_ratio_threshold 2.0
#                               the repetition loop survived at ratio 2.16 under the 2.4 default with both off;
#   multilingual=False          unrestricted LID translated Romanian to English.
DECODE_OPTIONS: dict[str, Any] = {
    "beam_size": 5,
    "best_of": 5,
    "patience": 1.0,
    "length_penalty": 1.0,
    "repetition_penalty": 1.1,
    "no_repeat_ngram_size": 4,
    "temperatures": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "compression_ratio_threshold": 2.0,
    "log_prob_threshold": -1.0,
    "no_speech_threshold": 0.6,
    "prompt_reset_on_temperature": 0.5,
    "condition_on_previous_text": False,
    "initial_prompt": None,
    "prefix": None,
    "word_timestamps": True,
    "hallucination_silence_threshold": 2.0,
    "without_timestamps": False,
    "max_initial_timestamp": 1.0,
    "suppress_blank": True,
    "suppress_tokens": [-1],
    "multilingual": False,
    "max_new_tokens": None,
    "clip_timestamps": "0",
    "prepend_punctuations": "\"'“¿([{-",
    "append_punctuations": "\"'.。,，!！?？:：”)]}、",
}

# Windows shorter than this carry no usable acoustic LID signal; they inherit the previous window's language.
LID_MIN_WINDOW_S = 4.0
# Text LID must be at least this confident to send a disagreeing window to the rescoring queue.
TEXT_DISAGREEMENT_MIN_CONFIDENCE = 0.70
GARBAGE_FLAG_REASON = "low_confidence_asr"
# A segment denser than this many characters per second is a hallucination stamped on a sliver of audio
# (measured: "Субтитры создавал DimaTorzok" = 28 chars in 0.14 s; real speech runs at ~15 chars/s).
GARBAGE_MAX_CHARS_PER_SECOND = 40.0
GARBAGE_MIN_CHARS_FOR_DENSITY = 10
# Hotword echo: the decoder copies the hint list instead of the audio (measured on the real recording:
# "ИВЛ, Кишинёв, реанимация, ИВЛ, КТ, МРТ, ЭКГ, норадреналин"). This many hint items in one window's
# text, or hint items making up this share of its words, triggers a hotword-free re-decode.
HOTWORD_ECHO_MIN_ITEMS = 3
HOTWORD_ECHO_MIN_SHARE = 0.5
ALPHA_RE = re.compile(r"[^\W\d_]", re.UNICODE)
WORD_RE = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)


def build_transcription_options(tokenizer: Tokenizer, hotwords: Optional[str]) -> TranscriptionOptions:
    """One TranscriptionOptions per decode: generate_segments mutates clip_timestamps in place."""
    options = dict(DECODE_OPTIONS)
    options["beam_size"] = settings.WHISPER_BEAM_SIZE
    options["suppress_tokens"] = get_suppressed_tokens(tokenizer, list(DECODE_OPTIONS["suppress_tokens"]))
    options["hotwords"] = hotwords
    return TranscriptionOptions(**options)


def restrict_language_probs(results: list[tuple[str, float]], allowed: list[str]) -> list[tuple[str, float]]:
    """
    Restricted acoustic LID: keeps only `allowed` languages from Whisper's language-token distribution
    and renormalises, sorted by probability (descending). `results` is one entry of
    ctranslate2 Whisper.detect_language(): [("<|ru|>", 0.61), ...].
    """
    probs = {token[2:-2]: float(prob) for token, prob in results}
    picked = [(lang, probs.get(lang, 0.0)) for lang in allowed]
    total = sum(p for _, p in picked)
    if total <= 0:
        return [(lang, 1.0 / len(allowed)) for lang in allowed]
    return sorted(((lang, p / total) for lang, p in picked), key=lambda item: item[1], reverse=True)


def stitch_segments(segments: list[Segment], window_start: float) -> list[Segment]:
    """Shifts window-relative segment and word times to absolute recording time (in place)."""
    for seg in segments:
        seg.start = round(seg.start + window_start, 2)
        seg.end = round(seg.end + window_start, 2)
        if seg.words:
            for word in seg.words:
                word.start = round(word.start + window_start, 2)
                word.end = round(word.end + window_start, 2)
    return segments


def needs_rescoring(acoustic_language: str, p1: float, text: TextLID, threshold: float) -> bool:
    """Rescoring queue rule: weak acoustic LID, or a confident text/acoustic disagreement."""
    if p1 < threshold:
        return True
    return text.is_concrete and text.language != acoustic_language and text.confidence >= TEXT_DISAGREEMENT_MIN_CONFIDENCE


def garbage_reason(text: str, avg_logprob: float, compression_ratio: float, no_speech_prob: float, duration: Optional[float] = None) -> Optional[str]:
    """Post-decode garbage filter; the segment is kept and flagged, never dropped."""
    if (
        compression_ratio > settings.ASR_GARBAGE_COMPRESSION
        or avg_logprob < settings.ASR_GARBAGE_LOGPROB
        or no_speech_prob > settings.ASR_GARBAGE_NO_SPEECH
        or not ALPHA_RE.search(text)
    ):
        return GARBAGE_FLAG_REASON
    if duration is not None and len(text) >= GARBAGE_MIN_CHARS_FOR_DENSITY and len(text) / max(duration, 0.01) > GARBAGE_MAX_CHARS_PER_SECOND:
        return GARBAGE_FLAG_REASON
    return None


def hotword_echo(text: str, hotwords: Optional[str]) -> bool:
    """True when the decoded text is (mostly) the hotword hint list read back instead of the audio."""
    if not hotwords or not text:
        return False
    items = {item.strip().lower() for item in hotwords.split(",") if item.strip()}
    words = [w.lower() for w in WORD_RE.findall(text)]
    if not words:
        return False
    hits = sum(1 for w in words if w in items)
    return hits >= HOTWORD_ECHO_MIN_ITEMS or hits / len(words) >= HOTWORD_ECHO_MIN_SHARE


@dataclass
class Hypothesis:
    """One forced-language decode of a window (absolute times)."""
    language: str
    segments: list[Segment]
    hotwords: Optional[str] = None

    @property
    def text(self) -> str:
        return " ".join(seg.text.strip() for seg in self.segments if seg.text.strip())

    @property
    def mean_logprob(self) -> float:
        if not self.segments:
            return float("-inf")
        return float(np.mean([seg.avg_logprob for seg in self.segments]))

    @property
    def words(self) -> list:
        return [word for seg in self.segments if seg.words for word in seg.words]


@dataclass
class WindowResult:
    """Decoded window after language reconciliation, before segment materialisation."""
    window: DecodeWindow
    ranking: list[tuple[str, float]]     # restricted acoustic LID, descending
    acoustic_language: str
    acoustic_p1: float
    inherited: bool
    chosen: Hypothesis
    language: str                        # ro | ru | en | mixed | und
    language_confidence: float
    language_source: str                 # acoustic | text | rescored
    text_lid: TextLID
    rescored: bool = False
    spans: list[dict] = field(default_factory=list)
    flag_reason: Optional[str] = None    # window-level reason (e.g. undetermined language)
    echo_redecoded: bool = False         # the hotword hint was echoed; decoded again without it


_BaseBatched = BatchedInferencePipeline if BatchedInferencePipeline is not None else object


class MedparkBatchedPipeline(_BaseBatched):
    """
    faster-whisper 1.2.1 BatchedInferencePipeline with RESTRICTED per-chunk language identification.

    generate_segment_batched() below is a copy of the upstream method
    (faster_whisper/transcribe.py lines 174-252) with two changes:
      - lines 210-220 (`prompts = [prompt.copy() ...]` and `if options.multilingual: ... prompts[i][language_token_index] = language_token`)
        are replaced: the language token is the restricted argmax over `allowed_languages` (unrestricted
        argmax translated Romanian to English), it is chosen for EVERY chunk unless `forced_language` is
        set, chunks shorter than LID_MIN_WINDOW_S inherit the previous chunk's language, and the
        decision is appended to `chunk_lids` so the caller can attribute segments to windows;
      - lines 182-191 (single prompt from options.hotwords) become per-chunk prompts so each chunk
        gets the hotwords of its own language. CTranslate2 4.8.2 requires <|startoftranscript|> at the
        same position in every prompt of a batch (verified: it raises otherwise), so shorter hotword
        sections are left-padded with whitespace tokens up to the longest one.
    Everything else (max_length check, generate() call, score recovery) is verbatim.
    """

    def __init__(self, model: WhisperModel, allowed_languages: list[str], forced_language: Optional[str] = None, hotwords_enabled: bool = True):
        super().__init__(model)
        self.allowed_languages = allowed_languages
        self.forced_language = forced_language
        self.hotwords_enabled = hotwords_enabled
        self.chunk_lids: list[dict] = []
        self._current_durations: list[float] = []
        self._previous_language: Optional[str] = forced_language

    def forward(self, features, tokenizer, chunks_metadata, options):
        self._current_durations = [float(meta["duration"]) for meta in chunks_metadata]
        return super().forward(features, tokenizer, chunks_metadata, options)

    def _equal_length_prompts(self, tokenizer: Tokenizer, chunk_languages: list[str], without_timestamps: bool) -> list[list[int]]:
        """
        [<|startofprev|>] + hotwords(language) + [<|startoftranscript|>, <|language|>, <|transcribe|>] per chunk,
        with every hotword section left-padded by " " tokens to the longest one so the SOT position is shared.
        """
        space = tokenizer.encode(" ")
        sections: list[list[int]] = []
        for language in chunk_languages:
            hotwords = hotwords_for(language) if self.hotwords_enabled else None
            sections.append(tokenizer.encode(" " + hotwords.strip()) if hotwords else [])
        longest = max(len(section) for section in sections)
        prompts = []
        for language, section in zip(chunk_languages, sections):
            language_token = tokenizer.tokenizer.token_to_id(f"<|{language}|>")
            prompt: list[int] = []
            if longest > 0:
                padding = longest - len(section)
                prompt.append(tokenizer.sot_prev)
                prompt.extend(space * padding)
                prompt.extend(section)
            prompt.extend([tokenizer.sot, language_token, tokenizer.task])
            if without_timestamps:
                prompt.append(tokenizer.no_timestamps)
            prompts.append(prompt)
        return prompts

    def generate_segment_batched(self, features: np.ndarray, tokenizer: Tokenizer, options: TranscriptionOptions):
        batch_size = features.shape[0]

        prompt = self.model.get_prompt(
            tokenizer,
            previous_tokens=(tokenizer.encode(options.initial_prompt) if options.initial_prompt is not None else []),
            without_timestamps=options.without_timestamps,
            hotwords=None,
        )

        if options.max_new_tokens is not None:
            max_length = len(prompt) + options.max_new_tokens
        else:
            max_length = self.model.max_length

        if max_length > self.model.max_length:
            raise ValueError(
                f"The length of the prompt is {len(prompt)}, and the `max_new_tokens` "
                f"{max_length - len(prompt)}. Thus, the combined length of the prompt "
                f"and `max_new_tokens` is: {max_length}. This exceeds the "
                f"`max_length` of the Whisper model: {self.model.max_length}. "
                "You should either reduce the length of your prompt, or "
                "reduce the value of `max_new_tokens`, "
                f"so that their combined length is less that {self.model.max_length}."
            )

        encoder_output = self.model.encode(features)

        # --- Medpark change: restricted per-chunk LID (replaces the `options.multilingual` block) ---
        if self.forced_language is not None:
            detections = [None] * batch_size
        else:
            detections = self.model.model.detect_language(encoder_output)
        chunk_languages: list[str] = []
        for i in range(batch_size):
            duration = self._current_durations[i] if i < len(self._current_durations) else 0.0
            if self.forced_language is not None:
                ranking, language, p1, inherited = [(self.forced_language, 1.0)], self.forced_language, 1.0, False
            else:
                ranking = restrict_language_probs(detections[i], self.allowed_languages)
                language, p1 = ranking[0]
                inherited = False
                if duration < LID_MIN_WINDOW_S and self._previous_language is not None:
                    language = self._previous_language
                    p1 = dict(ranking).get(language, p1)
                    inherited = True
            self._previous_language = language
            chunk_languages.append(language)
            self.chunk_lids.append({"language": language, "p1": p1, "ranking": ranking, "inherited": inherited, "duration": duration})

        prompts = self._equal_length_prompts(tokenizer, chunk_languages, options.without_timestamps)
        # --- end Medpark change ---

        results = self.model.model.generate(
            encoder_output,
            prompts,
            beam_size=options.beam_size,
            patience=options.patience,
            length_penalty=options.length_penalty,
            max_length=max_length,
            suppress_blank=options.suppress_blank,
            suppress_tokens=options.suppress_tokens,
            return_scores=True,
            return_no_speech_prob=True,
            sampling_temperature=options.temperatures[0],
            repetition_penalty=options.repetition_penalty,
            no_repeat_ngram_size=options.no_repeat_ngram_size,
        )

        output = []
        for result in results:
            # return scores
            seq_len = len(result.sequences_ids[0])
            cum_logprob = result.scores[0] * (seq_len**options.length_penalty)

            output.append(
                dict(
                    avg_logprob=cum_logprob / (seq_len + 1),
                    no_speech_prob=result.no_speech_prob,
                    tokens=result.sequences_ids[0],
                )
            )

        return encoder_output, output


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
        self.last_run_stats: dict[str, Any] = {}
        self.last_window_results: list[WindowResult] = []  # diagnostics for scripts/asr_ab_benchmark.py
        self._prompt_warning_logged = False

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
        Transcribes audio with per-window language identification and automatic CPU fallback.

        `language=None` runs restricted LID over settings.WHISPER_LANGUAGES for every window; a code
        such as "ro" forces that language for every window. `initial_prompt` is ignored on purpose.
        """
        if not audio_path.exists():
            raise ASREngineError(f"Audio file does not exist: {audio_path}")

        if initial_prompt and not self._prompt_warning_logged:
            logger.warning(
                "initial_prompt is ignored: Whisper prompt conditioning was removed on purpose (it hallucinated "
                "the glossary as speech); per-window hotwords are used instead."
            )
            self._prompt_warning_logged = True
        if language is not None and language not in settings.WHISPER_LANGUAGES:
            raise ASREngineError(f"Limba '{language}' nu este acceptată; limbi configurate: {', '.join(settings.WHISPER_LANGUAGES)}.")

        strategy = settings.WHISPER_STRATEGY
        logger.info(f"Starting ASR transcription on {audio_path.name} (strategy={strategy}, languages={settings.WHISPER_LANGUAGES}, forced={language})...")

        # cuBLAS is loaded lazily at the first matrix multiply, so a CUDA runtime failure surfaces
        # HERE rather than at model load. It is only downgraded to CPU when explicitly allowed.
        try:
            return self._run_transcription(audio_path, language, strategy)
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
                    return self._run_transcription(audio_path, language, strategy)
                except Exception as fallback_error:
                    logger.error(f"CPU fallback transcription also failed: {fallback_error}")
                    raise ASREngineError(f"ASR transcription failed after CPU fallback: {fallback_error}")
            else:
                logger.error(f"Error during speech transcription: {e}")
                raise ASREngineError(f"ASR transcription failed: {e}")

    # ------------------------------------------------------------------ run

    @staticmethod
    def _load_audio(audio_path: Path) -> np.ndarray:
        """16 kHz mono float32 PCM. The pipeline hands over normalized WAV; anything else goes through PyAV."""
        try:
            import soundfile as sf
            audio, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if sample_rate == SAMPLE_RATE:
                return np.ascontiguousarray(audio, dtype=np.float32)
        except Exception as error:  # not a WAV soundfile understands: fall through to ffmpeg/PyAV
            logger.debug(f"soundfile could not read {audio_path.name} ({error}); using PyAV decode.")
        return decode_audio(str(audio_path), sampling_rate=SAMPLE_RATE)

    def _run_transcription(self, audio_path: Path, language: Optional[str], strategy: str) -> list[TranscriptSegment]:
        model = self.load_model()
        t_start = time.perf_counter()
        audio = self._load_audio(audio_path)
        audio_seconds = audio.shape[0] / SAMPLE_RATE

        t_vad = time.perf_counter()
        regions = speech_regions(audio)
        windows = pack_windows(
            regions,
            min_s=settings.ASR_WINDOW_MIN_S,
            target_s=settings.ASR_WINDOW_TARGET_S,
            max_s=settings.ASR_WINDOW_MAX_S,
            hard_cap_s=settings.ASR_WINDOW_HARD_CAP_S,
        )
        seconds_vad = time.perf_counter() - t_vad
        logger.info(
            f"VAD: {len(regions)} speech regions -> {len(windows)} decode windows "
            f"(speech {sum(w.speech_seconds for w in windows):.1f} s of {audio_seconds:.1f} s) in {seconds_vad:.1f} s"
        )

        t_decode = time.perf_counter()
        if strategy == "batched":
            results = self._decode_batched(model, audio, windows, language)
        else:
            results = self._decode_windowed(model, audio, windows, language)
        seconds_decode = time.perf_counter() - t_decode

        segments = self._materialize(results)
        self.last_window_results = results
        seconds_total = time.perf_counter() - t_start
        self.last_run_stats = self._build_stats(strategy, windows, results, segments, audio_seconds, seconds_vad, seconds_decode, seconds_total)

        if not segments:
            logger.info("No intelligible speech detected in audio file.")
        logger.info(
            f"Transcription complete: {len(segments)} segments from {len(windows)} windows "
            f"(languages {self.last_run_stats['window_languages']}, rescored {self.last_run_stats['rescored_windows']}, "
            f"RTF {self.last_run_stats['rtf']})."
        )
        return segments

    # ------------------------------------------------------------------ windowed strategy

    def _decode_hypothesis(self, model: WhisperModel, features: np.ndarray, encoder_output, language: str, window: DecodeWindow, use_hotwords: bool = True) -> Hypothesis:
        """Forced-language decode of one window from its cached encoder output; times made absolute."""
        tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task="transcribe", language=language)
        hotwords = hotwords_for(language) if (use_hotwords and settings.ASR_HOTWORDS_ENABLED) else None
        options = build_transcription_options(tokenizer, hotwords)
        # encoder_output is honoured while seek == 0, i.e. for the whole window (<= 28 s < 30 s).
        segments = list(model.generate_segments(features, tokenizer, options, False, encoder_output=encoder_output))
        return Hypothesis(language=language, segments=stitch_segments(segments, window.start), hotwords=hotwords)

    def _decode_windowed(self, model: WhisperModel, audio: np.ndarray, windows: list[DecodeWindow], forced_language: Optional[str]) -> list[WindowResult]:
        results: list[WindowResult] = []
        previous_language: Optional[str] = forced_language
        nb_max_frames = model.feature_extractor.nb_max_frames
        for window in windows:
            features = model.feature_extractor(window.slice(audio))
            encoder_output = model.encode(pad_or_trim(features[..., :nb_max_frames]))

            inherited = False
            if forced_language is not None:
                ranking = [(forced_language, 1.0)]
                acoustic_language, p1 = forced_language, 1.0
            else:
                ranking = restrict_language_probs(model.model.detect_language(encoder_output)[0], settings.WHISPER_LANGUAGES)
                acoustic_language, p1 = ranking[0]
                if window.duration < LID_MIN_WINDOW_S and previous_language is not None:
                    acoustic_language = previous_language
                    p1 = dict(ranking).get(previous_language, p1)
                    inherited = True

            first = self._decode_hypothesis(model, features, encoder_output, acoustic_language, window)
            echoed = hotword_echo(first.text, first.hotwords)
            if echoed:
                first = self._decode_hypothesis(model, features, encoder_output, acoustic_language, window, use_hotwords=False)
            result = self._reconcile(window, ranking, acoustic_language, p1, inherited, first, forced=forced_language is not None)
            result.echo_redecoded = echoed
            if result.rescored is None:  # queued: second hypothesis from the same encoder output
                alternative = self._alternative_language(result)
                second = self._decode_hypothesis(model, features, encoder_output, alternative, window, use_hotwords=not echoed)
                result = self._pick_rescored(result, second)
            results.append(result)
            previous_language = result.language if result.language in settings.WHISPER_LANGUAGES else previous_language
        return results

    # ------------------------------------------------------------------ batched strategy

    def _decode_batched(self, model: WhisperModel, audio: np.ndarray, windows: list[DecodeWindow], forced_language: Optional[str]) -> list[WindowResult]:
        if not windows:
            return []
        pipeline = MedparkBatchedPipeline(model, settings.WHISPER_LANGUAGES, forced_language, settings.ASR_HOTWORDS_ENABLED)
        tokenizer_language = forced_language or settings.WHISPER_LANGUAGES[0]
        options = {k: v for k, v in DECODE_OPTIONS.items() if k not in ("temperatures", "clip_timestamps", "multilingual", "suppress_tokens", "condition_on_previous_text", "prompt_reset_on_temperature", "max_initial_timestamp", "hallucination_silence_threshold")}
        options["beam_size"] = settings.WHISPER_BEAM_SIZE
        options["temperature"] = DECODE_OPTIONS["temperatures"]
        options["suppress_tokens"] = list(DECODE_OPTIONS["suppress_tokens"])
        segments_iter, _info = pipeline.transcribe(
            audio,
            language=tokenizer_language,  # per-chunk token is overridden inside generate_segment_batched
            vad_filter=False,
            clip_timestamps=[{"start": w.start, "end": w.end} for w in windows],
            chunk_length=settings.WHISPER_CHUNK_LENGTH_S,
            batch_size=settings.WHISPER_BATCH_SIZE,
            hotwords=None,
            **options,
        )
        # Segment.seek identifies the chunk: int(offset * frames_per_second) with offset = int(start * sr) / sr.
        seek_to_window = {int((int(w.start * SAMPLE_RATE) / SAMPLE_RATE) * model.frames_per_second): i for i, w in enumerate(windows)}
        per_window: dict[int, list[Segment]] = {i: [] for i in range(len(windows))}
        for seg in segments_iter:
            index = seek_to_window.get(seg.seek)
            if index is None:  # nearest window by start time; should not happen
                index = min(range(len(windows)), key=lambda i: abs(windows[i].start - seg.start))
            seg.start, seg.end = round(seg.start, 2), round(seg.end, 2)
            if seg.words:
                for word in seg.words:
                    word.start, word.end = round(word.start, 2), round(word.end, 2)
            per_window[index].append(seg)
        if len(pipeline.chunk_lids) != len(windows):
            raise ASREngineError(f"Batched decode returned LID for {len(pipeline.chunk_lids)} chunks but {len(windows)} windows were sent.")

        results: list[WindowResult] = []
        followup: list[WindowResult] = []
        forced = forced_language is not None
        for window, lid in zip(windows, pipeline.chunk_lids):
            hypothesis = Hypothesis(language=lid["language"], segments=per_window[window.index], hotwords=hotwords_for(lid["language"]) if settings.ASR_HOTWORDS_ENABLED else None)
            result = self._reconcile(window, lid["ranking"], lid["language"], lid["p1"], lid["inherited"], hypothesis, forced=forced)
            result.echo_redecoded = hotword_echo(hypothesis.text, hypothesis.hotwords)
            results.append(result)
            if result.rescored is None or result.echo_redecoded:
                followup.append(result)

        # Echoed and queued windows are re-encoded once and decoded sequentially (same code path as "windowed").
        nb_max_frames = model.feature_extractor.nb_max_frames
        for result in followup:
            window = result.window
            features = model.feature_extractor(window.slice(audio))
            encoder_output = model.encode(pad_or_trim(features[..., :nb_max_frames]))
            if result.echo_redecoded:
                first = self._decode_hypothesis(model, features, encoder_output, result.acoustic_language, window, use_hotwords=False)
                result = self._reconcile(window, result.ranking, result.acoustic_language, result.acoustic_p1, result.inherited, first, forced=forced)
                result.echo_redecoded = True
            if result.rescored is None:
                second = self._decode_hypothesis(model, features, encoder_output, self._alternative_language(result), window, use_hotwords=not result.echo_redecoded)
                result = self._pick_rescored(result, second)
            results[window.index] = result
        return results

    # ------------------------------------------------------------------ reconciliation

    def _reconcile(self, window: DecodeWindow, ranking: list[tuple[str, float]], acoustic_language: str, p1: float, inherited: bool, hypothesis: Hypothesis, forced: bool) -> WindowResult:
        """
        Decides the window language from acoustic LID and the text of its decode.
        `rescored` is None when the window is queued for a second hypothesis, False otherwise.
        """
        text = detect_text_language(hypothesis.text)
        result = WindowResult(
            window=window, ranking=ranking, acoustic_language=acoustic_language, acoustic_p1=p1, inherited=inherited,
            chosen=hypothesis, language=acoustic_language, language_confidence=round(p1, 3), language_source="acoustic", text_lid=text, rescored=False,
        )
        if not hypothesis.segments:
            return result
        if text.language == "und":
            if text.letters == 0:
                result.language, result.language_confidence, result.language_source = "und", 0.0, "text"
                result.flag_reason = GARBAGE_FLAG_REASON
            return result  # Latin text without stopword evidence: the acoustic decision stands
        if text.language == "mixed":
            result.language, result.language_confidence, result.language_source = "mixed", text.confidence, "text"
            result.spans = language_spans(hypothesis.words, acoustic_language)
            return result
        if forced:
            return result
        threshold = settings.ASR_LID_RESCORE_BELOW
        if needs_rescoring(acoustic_language, p1, text, threshold):
            result.rescored = None
        else:
            self._relabel_from_text(result)
        return result

    def _alternative_language(self, result: WindowResult) -> str:
        """Second hypothesis: the confident text language when it disagrees, else the acoustic runner-up."""
        text = result.text_lid
        if text.is_concrete and text.language != result.acoustic_language and text.language in settings.WHISPER_LANGUAGES:
            return text.language
        for language, _ in result.ranking:
            if language != result.acoustic_language:
                return language
        return result.acoustic_language

    def _pick_rescored(self, result: WindowResult, second: Hypothesis) -> WindowResult:
        """Keeps the hypothesis with the better mean avg_logprob; the margin becomes the confidence."""
        first = result.chosen
        winner, loser = (second, first) if second.mean_logprob > first.mean_logprob else (first, second)
        margin = winner.mean_logprob - loser.mean_logprob if np.isfinite(loser.mean_logprob) else 1.0
        result.chosen = winner
        result.rescored = True
        result.language_source = "rescored"
        result.language = winner.language
        result.language_confidence = round(min(1.0, 0.5 + max(0.0, margin)), 3)
        result.text_lid = detect_text_language(winner.text)
        result.spans = []
        if result.text_lid.language == "mixed":
            result.language = "mixed"
            result.spans = language_spans(winner.words, winner.language)
        else:
            self._relabel_from_text(result)
        logger.debug(
            f"Rescored window {result.window.index} [{result.window.start:.1f}-{result.window.end:.1f}s]: "
            f"{first.language} {first.mean_logprob:.2f} vs {second.language} {second.mean_logprob:.2f} -> {winner.language}"
        )
        return result

    def _relabel_from_text(self, result: WindowResult) -> None:
        """
        Whisper decodes Romanian speech under the <|en|> token as Romanian text more often than it
        translates it (measured); the label must follow the confident text language in that case.
        Only Latin-script swaps (ro <-> en) are relabelled: Cyrillic under <|ru|> is Russian by construction.
        """
        text = result.text_lid
        if text.is_concrete and text.language in ("ro", "en") and result.language in ("ro", "en") \
                and text.language != result.language and text.confidence >= TEXT_DISAGREEMENT_MIN_CONFIDENCE:
            result.language = text.language
            result.language_source = "text"
            result.language_confidence = text.confidence

    # ------------------------------------------------------------------ segments

    def _materialize(self, results: list[WindowResult]) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for result in results:
            for seg in result.chosen.segments:
                text = seg.text.strip()
                if not text:
                    continue
                corrections: list[dict] = []
                if settings.ASR_LEXICON_ENABLED and result.language in ("ro", "ru", "en"):
                    text, corrections = correct_segment(text, result.language)

                spans = [s for s in result.spans if s["end"] > seg.start and s["start"] < seg.end] if result.spans else []
                reason = result.flag_reason or garbage_reason(text, seg.avg_logprob, seg.compression_ratio, seg.no_speech_prob, seg.end - seg.start)
                if reason is None:
                    is_flagged, reason = self._check_review_flags(text, seg.avg_logprob)
                else:
                    is_flagged = True

                segments.append(TranscriptSegment(
                    start=seg.start,
                    end=max(seg.end, seg.start + 0.01),
                    speaker="Speaker 1",
                    raw_text=text,
                    language=result.language,
                    language_confidence=result.language_confidence,
                    language_source=result.language_source,
                    language_spans=spans,
                    corrections=corrections,
                    window_index=result.window.index,
                    asr_avg_logprob=round(float(seg.avg_logprob), 4),
                    asr_compression_ratio=round(float(seg.compression_ratio), 4),
                    asr_no_speech_prob=round(float(seg.no_speech_prob), 4),
                    confidence=round(min(1.0, max(0.0, 1.0 + (seg.avg_logprob / 5.0))), 2),
                    is_flagged=is_flagged,
                    flag_reason=reason,
                ))
        segments.sort(key=lambda s: (s.start, s.end))
        return segments

    def _build_stats(self, strategy, windows, results, segments, audio_seconds, seconds_vad, seconds_decode, seconds_total) -> dict[str, Any]:
        window_languages = {lang: 0 for lang in settings.WHISPER_LANGUAGES}
        for r in results:
            if r.language in window_languages:
                window_languages[r.language] += 1
            else:
                window_languages[r.language] = window_languages.get(r.language, 0) + 1
        durations = [round(s.end - s.start, 2) for s in segments]
        integer_durations = sum(1 for d in durations if abs(d - round(d)) < 1e-9)
        zero_gaps = sum(1 for a, b in zip(segments, segments[1:]) if abs(b.start - a.end) < 1e-9)
        decided = [r for r in results if r.chosen.segments and r.text_lid.is_concrete and r.language in ("ro", "ru", "en")]
        agreement = sum(1 for r in decided if r.text_lid.language == r.language) / len(decided) if decided else None
        logprobs = [s.asr_avg_logprob for s in segments if s.asr_avg_logprob is not None]
        return {
            "strategy": strategy,
            "model": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "languages": list(settings.WHISPER_LANGUAGES),
            "windows": len(windows),
            "window_languages": window_languages,
            "inherited_windows": sum(1 for r in results if r.inherited),
            "rescored_windows": sum(1 for r in results if r.rescored),
            "hotword_echo_windows": sum(1 for r in results if r.echo_redecoded),
            "segments": len(segments),
            "garbage_flagged": sum(1 for s in segments if s.flag_reason == GARBAGE_FLAG_REASON),
            "corrections": sum(len(s.corrections) for s in segments),
            "integer_second_durations": integer_durations,
            "zero_gaps": zero_gaps,
            "text_acoustic_agreement": round(agreement, 3) if agreement is not None else None,
            "mean_avg_logprob": round(float(np.mean(logprobs)), 4) if logprobs else None,
            "seconds_vad": round(seconds_vad, 2),
            "seconds_encode_decode": round(seconds_decode, 2),
            "seconds_total": round(seconds_total, 2),
            "audio_seconds": round(audio_seconds, 2),
            "rtf": round(seconds_total / audio_seconds, 4) if audio_seconds > 0 else None,
        }

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
