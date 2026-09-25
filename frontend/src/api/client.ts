// Medpark Meeting Intelligence System - API Client

import {
  ApprovalResponse,
  Meeting,
  MeetingCreate,
  Transcript,
  MinutesOfMeeting,
  DeliveryRecord,
} from '../types';

const API_BASE = '/api/v1';

// A stalled backend must not freeze the UI: every JSON call is bounded by an AbortController.
const REQUEST_TIMEOUT_MS = 15000;
const UPLOAD_TIMEOUT_MS = 180000;

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
};
