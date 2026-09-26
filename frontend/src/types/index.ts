// Medpark Meeting Intelligence System - Frontend TypeScript Contracts

export type MeetingType = 'medical' | 'executive' | 'administrative';
export type WorkflowMode = 'supervised' | 'auto_pilot';
export type ProcessingStatus = 
  | 'idle' 
  | 'uploading' 
  | 'preprocessing' 
  | 'transcribing' 
  | 'diarizing' 
  | 'extracting' 
  | 'generating_docs' 
  | 'completed' 
  | 'failed';

export type ReviewStatus = 'draft' | 'pending_review' | 'approved' | 'delivered';

export interface Attendee {
  id: string;
  name: string;
  role: string;
  email: string;
  department?: string;
  person_id?: string;
}

export interface Meeting {
  id: string;
  title: string;
  meeting_type: MeetingType;
  workflow_mode: WorkflowMode;
  scheduled_at: string;
  attendees: Attendee[];
  agenda?: string;
  distribution_list: string[];
  created_at: string;
  updated_at: string;
  original_audio_path?: string;
  normalized_audio_path?: string;
  audio_duration_seconds: number;
  processing_status: ProcessingStatus;
  processing_progress: number;
  current_stage_detail?: string;
  review_status: ReviewStatus;
  current_revision: number;
  approved_by?: string;
  approved_at?: string;
  processing_time_seconds: number;
  error_message?: string;
  // Device Whisper actually ran on for the last pipeline run ("cuda" / "cpu"); absent on older records.
  asr_device_used?: string | null;
  // Telemetry of the last ASR run (strategy, windows, window_languages, rtf, ...); empty/absent on old records.
  asr_stats?: AsrRunStats;
}

// Free-form telemetry copied from whisper_engine.last_run_stats; every key is optional.
export interface AsrRunStats {
  strategy?: string;
  device?: string;
  compute_type?: string;
  windows?: number;
  window_languages?: Record<string, number>;
  rescored_windows?: number;
  garbage_flagged?: number;
  integer_second_durations?: number;
  zero_gaps?: number;
  seconds_vad?: number;
  seconds_encode_decode?: number;
  seconds_total?: number;
  audio_seconds?: number;
  rtf?: number;
  [key: string]: unknown;
}

export interface MeetingCreate {
  title: string;
  meeting_type: MeetingType;
  workflow_mode: WorkflowMode;
  scheduled_at: string;
  attendees: Attendee[];
  agenda?: string;
  distribution_list: string[];
}

// Speaker attribution lifecycle (V3). `speaker` is ALWAYS the anonymous "Speaker N" label; a
// person's name is only ever readable through `display_speaker`, which the backend computes as
// confirmed_display_name when the segment is printable and the anonymous label otherwise.
export type AttributionState = 'anonymous' | 'suggested' | 'confirmed' | 'corrected';
export type MatchBand = 'strong' | 'moderate' | 'weak' | 'no_match';

export interface SpeakerSuggestion {
  person_id: string;
  person_name: string;
  score: number; // cosine similarity, not a probability
  margin: number; // top1 - top2
  band: MatchBand;
  space_id: string;
}

// Code-switching ASR: which stage decided a segment's language. "legacy" = stamped by the old
// single whole-file pass (persisted before per-window language identification existed).
export type LanguageSource = 'acoustic' | 'text' | 'rescored' | 'manual' | 'legacy';
export type SpanLanguage = 'ro' | 'ru' | 'en';

// A contiguous run of one language inside a "mixed" segment, in absolute audio seconds.
export interface LanguageSpan {
  start: number;
  end: number;
  language: SpanLanguage;
}

// A clinical-lexicon substitution the ASR post-processor already applied to raw_text.
export interface Correction {
  was: string;
  now: string;
  score: number; // match score of the lexicon rule, not a probability
}

export interface TranscriptSegment {
  id: string;
  start: number;
  end: number;
  speaker: string; // anonymous label, pattern ^Speaker \d+$
  // Confirmed Person.id; non-null only when attribution_state is confirmed or corrected.
  speaker_id?: string | null;
  raw_text: string;
  corrected_text?: string;
  display_text: string;
  language: string; // ro | ru | en | mixed | und (older records may hold other whisper codes)
  confidence: number;
  is_flagged: boolean;
  flag_reason?: string;
  // Per-window language identification (all optional so pre-code-switching transcripts still type-check).
  language_confidence?: number; // restricted-LID probability of `language`, 0 on legacy records
  language_source?: LanguageSource;
  language_spans?: LanguageSpan[]; // only populated when language === 'mixed'
  corrections?: Correction[]; // lexicon corrections already applied; the decoder output is in `was`
  window_index?: number | null;
  asr_avg_logprob?: number | null;
  asr_compression_ratio?: number | null;
  asr_no_speech_prob?: number | null;
  // V3 attribution fields (all optional so pre-voice-id transcripts still type-check).
  cluster_id?: string | null; // "SPEAKER_01"
  attribution_state?: AttributionState;
  confirmed_display_name?: string | null; // snapshot of the person's name at confirm time
  confirmed_by?: string | null;
  confirmed_at?: string | null;
  confirmed_for_revision?: number | null;
  suggestion?: SpeakerSuggestion | null;
  suggested_identity?: string | null; // mirror of suggestion.person_name; reviewer prompt only
  speech_seconds?: number | null; // VAD speech inside the segment
  printable_name?: boolean; // confirmed/corrected AND enough speech to carry a name
  display_speaker?: string; // the ONLY accessor renderers may use for a name
  legacy_speaker_id?: string | null;
  legacy_speaker_label?: string | null;
}

export interface Transcript {
  meeting_id: string;
  segments: TranscriptSegment[];
  languages_detected: string[];
  total_words: number;
  duration_seconds: number;
}

export interface EvidenceQuote {
  segment_id: string;
  start: number;
  end: number;
  quote: string;
  speaker?: string;
  // Set by the speaker confirmation write path once the cited segment is printable.
  speaker_person_id?: string | null;
  speaker_is_confirmed?: boolean;
}

export interface DecisionItem {
  id: string;
  topic: string;
  decision: string;
  category: 'clinical' | 'budget' | 'operations' | 'protocol';
  evidence: EvidenceQuote[];
  is_reviewed: boolean;
}

// How the owner string was resolved by the validator:
// roster = fuzzy-matched to an attendee, mention = verbatim non-roster name (needs human confirmation),
// speaker = anonymous "Speaker N" label, unassigned = nothing grounded in the cited evidence,
// confirmed_speaker = a "Speaker N" owner whose cluster a human reviewer confirmed to a person.
export type OwnerSource = 'roster' | 'mention' | 'speaker' | 'unassigned' | 'confirmed_speaker';

export interface ActionItem {
  id: string;
  task: string;
  owner: string;
  deadline_phrase?: string;
  deadline_date?: string;
  priority: 'high' | 'medium' | 'low';
  status: 'open' | 'in_progress' | 'completed' | 'cancelled';
  evidence: EvidenceQuote[];
  is_reviewed: boolean;
  owner_source?: OwnerSource;
}

export interface RiskOrQuestionItem {
  id: string;
  item_type: 'risk' | 'unresolved_question';
  description: string;
  severity: 'high' | 'medium' | 'low';
  evidence: EvidenceQuote[];
}

// Free-form telemetry written by the extraction engine; every key is optional on old records.
export interface ExtractionStats {
  engine?: string;
  model?: string;
  chunks?: number;
  calls?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  seconds?: number;
  json_first_pass_rate?: number;
  [key: string]: unknown;
}

export interface MinutesOfMeeting {
  meeting_id: string;
  title: string;
  meeting_type: string;
  summary_ro: string;
  summary_ru?: string | null;
  summary_en?: string;
  agenda_topics: string[];
  decisions: DecisionItem[];
  action_items: ActionItem[];
  risks_and_questions: RiskOrQuestionItem[];
  generated_at: string;
  model_version: string;
  revision: number;
  pdf_path?: string;
  docx_path?: string;
  // Provenance and review flags (optional so persisted pre-LLM payloads still type-check).
  is_degraded?: boolean; // heuristic fallback produced this document; backend refuses dispatch
  needs_name_review?: boolean; // a non-roster owner or a suspect proper noun exists
  failed_chunks?: number[]; // transcript chunk ordinals that failed extraction twice
  extraction_stats?: ExtractionStats;
}

export interface DeliveryRecord {
  id: string;
  meeting_id: string;
  revision: number;
  channel: string;
  recipients: string[];
  subject: string;
  status: 'pending' | 'dispatched' | 'failed' | 'simulated';
  pdf_attachment_path?: string;
  docx_attachment_path?: string;
  sent_at?: string;
  error_message?: string;
  smtp_response_code?: number;
  idempotency_key?: string;
}

export interface ApprovalResponse {
  meeting_id: string;
  status: ReviewStatus;
  approved_by: string;
  approved_at: string;
  revision: number;
  delivery_record?: DeliveryRecord | null;
}

// GET /ready (served at the app root, not under /api/v1).
export interface LlmServiceReadiness {
  endpoint: string;
  engine?: string;
  model?: string;
  connected: boolean;
  loaded?: boolean;
  mode: 'neural_server' | 'unavailable' | string;
}

// Voice identification block of /ready. `enabled` is the feature flag AND embedder availability;
// when the ONNX model is missing the backend reports enabled=false with a plain-text reason.
export interface VoiceIdReadiness {
  enabled: boolean;
  reason: string;
  embedder_available: boolean;
  model: string;
  dim: number | null;
  space_id: string | null;
  enrolled_people: number;
}

// ASR block of /ready. `device` is the configured setting ("auto"/"cuda"/"cpu"); `resolved_device` is what
// Whisper actually runs on. `code_switching` is true when per-window restricted language identification
// is active (strategy windowed/batched). The last four keys are absent on backends built before it.
export interface AsrServiceReadiness {
  model_name?: string;
  cached_locally?: boolean;
  device?: string;
  resolved_device?: string;
  strategy?: string;
  languages?: string[];
  code_switching?: boolean;
  provider?: string;
  endpoint?: string;
  connected?: boolean;
  ready?: boolean;
  queue_depth?: number;
}

export interface ReadinessResponse {
  ready: boolean;
  storage?: { ready: boolean; data_dir: string };
  asr_service?: AsrServiceReadiness;
  llm_service?: LlmServiceReadiness;
  smtp_service?: { host: string; reachable: boolean };
  voice_id?: VoiceIdReadiness;
}

// ---------------------------------------------------------------------------------------------
// Voice identification: people, enrollment and per-meeting speaker clusters (V2, V5, V7).
// ---------------------------------------------------------------------------------------------

// needs_reenrollment = the person's only voiceprints were made by a different embedder space.
export type EnrollmentState = 'not_enrolled' | 'enrolled' | 'needs_reenrollment';

// == backend PersonSummary. No endpoint ever returns an embedding vector.
export interface VoiceProfile {
  id: string;
  person_name: string;
  role: string;
  email: string;
  department?: string | null;
  title?: string | null;
  primary_language?: string | null;
  specialty?: string | null;
  state: EnrollmentState;
  sample_count: number;
  total_sample_seconds: number;
  embedding_model: string;
  embedding_model_version: string;
  consent_given_at?: string | null;
  enrolled_at?: string | null;
  last_used_at?: string | null;
  // Optional: why an enrollment with samples is still not_enrolled (e.g. not enough speech).
  quality_warnings?: string[];
}

export interface VoiceProfileCreate {
  person_name: string;
  role: string;
  email: string;
  department?: string;
  title?: string;
  primary_language?: string;
  specialty?: string;
}

export type SampleVerdict = 'good' | 'usable' | 'reject';

// Returned by POST /voice-profiles/{id}/samples; `reasons` are shown to the user verbatim.
export interface SampleQuality {
  duration_seconds: number;
  speech_seconds: number;
  mean_dbfs: number;
  clipped_fraction: number;
  verdict: SampleVerdict;
  reasons: string[];
}

// GET /voice-profiles/status
export interface VoiceStatus {
  enabled: boolean;
  embedder_available: boolean;
  space_id: string | null;
  model: string;
  dim: number | null;
  enrolled: number;
  not_enrolled: number;
  needs_reenrollment: number;
}

export interface ClusterSampleTurn {
  segment_id: string;
  start: number;
  end: number;
  text: string;
  speech_seconds: number;
}

export interface SpeakerCluster {
  cluster_id: string; // "SPEAKER_02"
  display_label: string; // "Speaker 2"
  total_speech_seconds: number;
  turn_count: number;
  state: AttributionState;
  suggested_profile_id?: string | null;
  suggested_name?: string | null;
  match_score?: number | null; // cosine similarity, never a probability
  match_band?: MatchBand | null;
  confirmed_profile_id?: string | null;
  confirmed_name?: string | null;
  confirmed_for_revision?: number | null;
  // The LOWEST-scoring turns against the candidate/confirmed voiceprint (up to 5), never the longest.
  sample_turns: ClusterSampleTurn[];
  sampled_seconds: number;
  printable_turns: number;
  unprintable_turns: number;
  blocking_reasons: string[]; // non-empty => confirmation refused (409) until resolved
  merge_suggestion_with: string[]; // other cluster ids that match the same person
}

export interface SpeakersResponse {
  clusters: SpeakerCluster[];
  embedder_available: boolean;
  space_id: string | null;
  enrolled_people: number;
  current_revision: number;
  warnings: string[];
}

export type SpeakerDecisionAction = 'confirm' | 'correct' | 'reject' | 'unknown';

export interface SpeakerConfirmRequest {
  action: SpeakerDecisionAction;
  profile_id?: string | null;
  expected_revision: number;
  reviewer_name: string;
  reviewer_role?: string;
}
