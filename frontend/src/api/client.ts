// Medpark Meeting Intelligence System - API Client

import {
  ApprovalResponse,
  Meeting,
  MeetingCreate,
  Transcript,
  MinutesOfMeeting,
  DeliveryRecord,
  ReadinessResponse,
  VoiceProfile,
  VoiceProfileCreate,
  SampleQuality,
  VoiceStatus,
  SpeakersResponse,
  SpeakerCluster,
  SpeakerConfirmRequest,
} from '../types';

const API_BASE = '/api/v1';

// A stalled backend must not freeze the UI: every JSON call is bounded by an AbortController.
const REQUEST_TIMEOUT_MS = 15000;
const UPLOAD_TIMEOUT_MS = 180000;
// /ready probes the LLM server (3 s budget) and the SMTP port (1 s) before answering.
const READINESS_TIMEOUT_MS = 8000;

async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs: number = REQUEST_TIMEOUT_MS
): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

export const apiClient = {
  // System readiness: root-level route, reports the local LLM/ASR/SMTP state truthfully.
  async getReadiness(): Promise<ReadinessResponse> {
    const res = await fetchWithTimeout('/ready', {}, READINESS_TIMEOUT_MS);
    if (!res.ok) throw new Error('Readiness probe failed');
    return res.json();
  },

  // Meetings
  async listMeetings(): Promise<Meeting[]> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/`);
    if (!res.ok) throw new Error('Failed to fetch meetings');
    return res.json();
  },

  async getMeeting(id: string): Promise<Meeting> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${id}`);
    if (!res.ok) throw new Error('Failed to fetch meeting');
    return res.json();
  },

  async createMeeting(payload: MeetingCreate): Promise<Meeting> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('Failed to create meeting');
    return res.json();
  },

  async deleteMeeting(id: string): Promise<void> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete meeting');
  },

  // Audio Upload
  async uploadAudio(meetingId: string, file: File): Promise<Meeting> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetchWithTimeout(
      `${API_BASE}/meetings/${meetingId}/audio/upload`,
      {
        method: 'POST',
        body: formData,
      },
      UPLOAD_TIMEOUT_MS
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to upload audio');
    }
    return res.json();
  },

  getAudioStreamUrl(meetingId: string): string {
    return `${API_BASE}/meetings/${meetingId}/audio/stream`;
  },

  // Pipeline Execution
  async startPipeline(meetingId: string): Promise<void> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/pipeline/start`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to start pipeline');
    }
  },

  async getPipelineStatus(meetingId: string): Promise<{
    meeting_id: string;
    status: string;
    progress: number;
    current_stage: string | null;
    processing_time_seconds: number;
    error_message: string | null;
  }> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/pipeline/status`);
    if (!res.ok) throw new Error('Failed to get pipeline status');
    return res.json();
  },

  // Transcript
  async getTranscript(meetingId: string): Promise<Transcript> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/transcript/`);
    if (!res.ok) throw new Error('Transcript not available');
    return res.json();
  },

  async updateSegment(
    meetingId: string,
    segmentId: string,
    update: { corrected_text?: string; speaker?: string }
  ): Promise<void> {
    const res = await fetchWithTimeout(
      `${API_BASE}/meetings/${meetingId}/transcript/segments/${segmentId}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(update),
      }
    );
    if (!res.ok) throw new Error('Failed to update segment');
  },

  // Minutes & Approval
  async getMinutes(meetingId: string): Promise<MinutesOfMeeting> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/minutes`);
    if (!res.ok) throw new Error('Minutes not available');
    return res.json();
  },

  async updateMinutes(
    meetingId: string,
    updatedMinutes: MinutesOfMeeting
  ): Promise<MinutesOfMeeting> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/minutes`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updatedMinutes),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update minutes');
    }
    return res.json();
  },

  async translateMinutes(
    meetingId: string,
    targetLang: 'ro' | 'ru' | 'en',
    force: boolean = false
  ): Promise<MinutesOfMeeting> {
    const res = await fetchWithTimeout(
      `${API_BASE}/meetings/${meetingId}/translate?target_lang=${targetLang}&force=${force}`,
      { method: 'POST' }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Translation failed');
    }
    return res.json();
  },

  async approveMeeting(
    meetingId: string,
    payload: {
      reviewer_name: string;
      reviewer_role: string;
      comments?: string;
      expected_revision?: number;
    }
  ): Promise<ApprovalResponse> {
    const res = await fetchWithTimeout(
      `${API_BASE}/meetings/${meetingId}/review/approve`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Approval failed');
    }
    return res.json();
  },

  // Deliveries & Downloads
  async listDeliveries(meetingId?: string): Promise<DeliveryRecord[]> {
    const url = meetingId
      ? `${API_BASE}/meetings/${meetingId}/deliveries`
      : `${API_BASE}/deliveries`;
    const res = await fetchWithTimeout(url);
    if (!res.ok) throw new Error('Failed to fetch deliveries');
    return res.json();
  },

  getPdfDownloadUrl(meetingId: string): string {
    return `${API_BASE}/meetings/${meetingId}/export/pdf`;
  },

  getDocxDownloadUrl(meetingId: string): string {
    return `${API_BASE}/meetings/${meetingId}/export/docx`;
  },

  // Delivery-scoped attachments: serve the exact revision that was dispatched,
  // not the current one.
  getDeliveryPdfUrl(deliveryId: string): string {
    return `${API_BASE}/deliveries/${deliveryId}/attachment/pdf`;
  },

  getDeliveryDocxUrl(deliveryId: string): string {
    return `${API_BASE}/deliveries/${deliveryId}/attachment/docx`;
  },

  // Voice profiles (people + enrollment). No call here ever returns an embedding vector, and
  // there is deliberately no way to enroll a person from meeting audio.
  // The collection routes are declared as "/" under the prefix, and the SPA static mount at "/"
  // swallows the slash-less path before Starlette can redirect it: keep the trailing slash
  // (same reason as /meetings/).
  async listVoiceProfiles(department?: string): Promise<VoiceProfile[]> {
    const url = department
      ? `${API_BASE}/voice-profiles/?department=${encodeURIComponent(department)}`
      : `${API_BASE}/voice-profiles/`;
    const res = await fetchWithTimeout(url);
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to fetch voice profiles'));
    return res.json();
  },

  async createVoiceProfile(payload: VoiceProfileCreate): Promise<VoiceProfile> {
    const res = await fetchWithTimeout(`${API_BASE}/voice-profiles/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to create voice profile'));
    return res.json();
  },

  async getVoiceProfile(id: string): Promise<VoiceProfile> {
    const res = await fetchWithTimeout(`${API_BASE}/voice-profiles/${id}`);
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to fetch voice profile'));
    return res.json();
  },

  async deleteVoiceProfile(id: string): Promise<void> {
    const res = await fetchWithTimeout(`${API_BASE}/voice-profiles/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to delete voice profile'));
  },

  // granted=false withdraws consent: the backend deletes every voiceprint and sample.
  async setVoiceConsent(id: string, granted: boolean): Promise<VoiceProfile> {
    const res = await fetchWithTimeout(`${API_BASE}/voice-profiles/${id}/consent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ granted }),
    });
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to update consent'));
    return res.json();
  },

  // Uploads one enrollment sample; a "reject" verdict stores nothing on the server.
  async uploadVoiceSample(id: string, file: File): Promise<SampleQuality> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetchWithTimeout(
      `${API_BASE}/voice-profiles/${id}/samples`,
      { method: 'POST', body: formData },
      UPLOAD_TIMEOUT_MS
    );
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to upload voice sample'));
    return res.json();
  },

  async wipeVoiceSamples(id: string): Promise<void> {
    const res = await fetchWithTimeout(`${API_BASE}/voice-profiles/${id}/samples`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to remove voice samples'));
  },

  async getVoiceStatus(): Promise<VoiceStatus> {
    const res = await fetchWithTimeout(`${API_BASE}/voice-profiles/status`);
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to fetch voice status'));
    return res.json();
  },

  // Per-meeting speaker clusters and the human confirmation write path.
  async getSpeakers(meetingId: string): Promise<SpeakersResponse> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/speakers`);
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Speaker clusters not available'));
    return res.json();
  },

  // Re-scores the cached segment embeddings after new enrollments; no audio is re-run.
  async rematchSpeakers(meetingId: string): Promise<SpeakersResponse> {
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/speakers/rematch`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Failed to re-match speakers'));
    return res.json();
  },

  // 409 = stale revision, blocking reasons, or an implicit many-to-one; the detail explains which.
  async confirmSpeaker(
    meetingId: string,
    clusterId: string,
    body: SpeakerConfirmRequest
  ): Promise<SpeakerCluster> {
    const res = await fetchWithTimeout(
      `${API_BASE}/meetings/${meetingId}/speakers/${clusterId}/confirm`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }
    );
    if (!res.ok) throw new Error(await readErrorDetail(res, 'Speaker decision was not recorded'));
    return res.json();
  },
};

// FastAPI reports failures as {detail: string | [{msg}]}; surface the text, never "[object Object]".
async function readErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const payload = await res.json();
    const detail = payload?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const msgs = detail.map((d: any) => d?.msg).filter((m: any) => typeof m === 'string');
      if (msgs.length > 0) return msgs.join('; ');
    }
  } catch {
    // Non-JSON body: fall through to the status-based message.
  }
  return `${fallback} (HTTP ${res.status})`;
}
