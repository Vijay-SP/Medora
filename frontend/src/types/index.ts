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

export interface TranscriptSegment {
  id: string;
  start: number;
  end: number;
  speaker: string;
  speaker_id?: string;
  raw_text: string;
  corrected_text?: string;
  display_text: string;
  language: string;
  confidence: number;
  is_flagged: boolean;
  flag_reason?: string;
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
}

export interface DecisionItem {
  id: string;
  topic: string;
  decision: string;
  category: 'clinical' | 'budget' | 'operations' | 'protocol';
  evidence: EvidenceQuote[];
  is_reviewed: boolean;
}

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
}

export interface RiskOrQuestionItem {
  id: string;
  item_type: 'risk' | 'unresolved_question';
  description: string;
  severity: 'high' | 'medium' | 'low';
  evidence: EvidenceQuote[];
}

export interface MinutesOfMeeting {
  meeting_id: string;
  title: string;
  meeting_type: string;
  summary_ro: string;
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
