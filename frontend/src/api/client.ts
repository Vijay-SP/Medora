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
  // names: "resolved" (server default) substitutes speaker tokens with confirmed/assigned names or
  // "Vorbitorul N"; "labels" returns the stored S<n> text (what PUT /minutes expects back).
  async getMinutes(meetingId: string, names?: 'resolved' | 'labels'): Promise<MinutesOfMeeting> {
    const minutes = await fetchMinutes(meetingId, names);
    if (names !== 'labels') rememberResolved(meetingId, minutes);
    return minutes;
  },

  // Callers edit the RESOLVED view (names / "Vorbitorul N" substituted), but storage must keep the
  // S<n> / "Speaker N" tokens so a name keeps depending on a human confirmation (a later reject makes
  // it anonymous again) and translation never sees a name. The payload is therefore rebased onto the
  // stored label text: every field the reviewer left untouched is sent in its stored form, and only
  // edited prose is kept, with rendered names mapped back to their tokens. Returns the resolved view.
  async updateMinutes(
    meetingId: string,
    updatedMinutes: MinutesOfMeeting
  ): Promise<MinutesOfMeeting> {
    const [stored, current] = await Promise.all([
      fetchMinutes(meetingId, 'labels'),
      fetchMinutes(meetingId, 'resolved'),
    ]);
    const payload = rebaseMinutesEdit(updatedMinutes, stored, [resolvedSnapshots.get(meetingId), current]);
    const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/minutes`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update minutes');
    }
    const saved: MinutesOfMeeting = await res.json();
    try {
      return await apiClient.getMinutes(meetingId);
    } catch {
      return saved; // stored token form; the caller's next reload resolves it
    }
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
    const minutes: MinutesOfMeeting = await res.json();
    rememberResolved(meetingId, minutes);
    return minutes;
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
  // 400 = a rejected label (action "label" with a bad display_label / unknown attendee_id).
  // The body carries profile_id for confirm/correct and display_label or attendee_id for label.
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

// ---------------------------------------------------------------------------------------------------
// Minutes edit rebasing (see updateMinutes). Mirrors backend services/extraction/attribution_render.py.

async function fetchMinutes(meetingId: string, names?: 'resolved' | 'labels'): Promise<MinutesOfMeeting> {
  const query = names ? `?names=${names}` : '';
  const res = await fetchWithTimeout(`${API_BASE}/meetings/${meetingId}/minutes${query}`);
  if (!res.ok) throw new Error('Minutes not available');
  return res.json();
}

// The last resolved view handed to a caller, i.e. what an editor most likely started from.
const resolvedSnapshots = new Map<string, MinutesOfMeeting>();

function rememberResolved(meetingId: string, minutes: MinutesOfMeeting): void {
  resolvedSnapshots.set(meetingId, JSON.parse(JSON.stringify(minutes)));
}

// Python's re `\b` is Unicode-aware; these lookarounds reproduce it so "ăS1" is not a token.
const WORD = '[\\p{L}\\p{N}\\p{M}_]';
const TOKEN_SOURCE = `(?<!${WORD})(?:S(\\d{1,2})|Speaker (\\d{1,2}))(?!${WORD})`;
const ANON_SOURCE = `(?<!${WORD})(?:Vorbitorul|Участник|Speaker) (\\d{1,2})(?!${WORD})`;
const TOKEN_WHOLE_RE = new RegExp(`^${TOKEN_SOURCE}$`, 'u');
const ANON_WHOLE_RE = new RegExp(`^${ANON_SOURCE}$`, 'u');
// Fields render_minutes substitutes in prose (ro, *_ru, *_en). Array elements inherit the parent key.
const PROSE_KEY_RE = /^(summary|agenda_topics|topic|decision|task|deadline_phrase|description)(_ro|_ru|_en)?$/;
const RENDERED_OWNER_SOURCES = new Set(['speaker', 'confirmed_speaker']);

type Json = unknown;
type Ctx = { key: string; parent: Record<string, Json> | null };

function isRecord(value: Json): value is Record<string, Json> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Learns which display name each speaker number rendered as, by aligning every stored string that
 * carries tokens with the same string in a resolved view ("S1 a propus" vs "Maria a propus").
 * Collects name -> speaker numbers; a name seen for more than one number is ambiguous.
 */
function collectRenderedNames(stored: Json, resolved: Json, out: Map<string, Set<string>>): void {
  if (typeof stored === 'string' && typeof resolved === 'string') {
    const numbers: string[] = [];
    const pieces: string[] = [];
    let last = 0;
    for (const match of stored.matchAll(new RegExp(TOKEN_SOURCE, 'gu'))) {
      const index = match.index ?? 0;
      numbers.push(String(Number(match[1] ?? match[2])));
      pieces.push(escapeRegExp(stored.slice(last, index)));
      last = index + match[0].length;
    }
    if (numbers.length === 0 || numbers.length > 12) return;
    pieces.push(escapeRegExp(stored.slice(last)));
    const aligned = new RegExp(`^${pieces.join('(.+?)')}$`, 'su').exec(resolved);
    if (!aligned) return;
    numbers.forEach((n, i) => {
      const name = aligned[i + 1].trim();
      if (!name || ANON_WHOLE_RE.test(name) || TOKEN_WHOLE_RE.test(name)) return;
      if (!out.has(name)) out.set(name, new Set());
      out.get(name)!.add(n);
    });
    return;
  }
  if (Array.isArray(stored) && Array.isArray(resolved)) {
    if (stored.length !== resolved.length) return;
    stored.forEach((item, i) => collectRenderedNames(item, resolved[i], out));
    return;
  }
  if (isRecord(stored) && isRecord(resolved)) {
    for (const key of Object.keys(stored)) collectRenderedNames(stored[key], resolved[key], out);
  }
}

/** Maps rendered speaker text in an edited string back to the stored token form. */
function unrenderLeaf(text: string, ctx: Ctx, names: Map<string, string>): string {
  if (PROSE_KEY_RE.test(ctx.key)) {
    const alternatives = [...names.keys()].sort((a, b) => b.length - a.length).map(escapeRegExp);
    const namePart = alternatives.length > 0 ? `|(?<!${WORD})(${alternatives.join('|')})(?!${WORD})` : '';
    const re = new RegExp(`${ANON_SOURCE}${namePart}`, 'gu');
    return text.replace(re, (whole: string, anonNumber?: string, name?: string) => {
      if (anonNumber) return `S${Number(anonNumber)}`;
      const n = name ? names.get(name) : undefined;
      return n ? `S${n}` : whole;
    });
  }
  const ownerRendered =
    ctx.key === 'owner' && RENDERED_OWNER_SOURCES.has(String(ctx.parent?.owner_source ?? ''));
  if (ctx.key === 'speaker' || ownerRendered) {
    const n = names.get(text.trim());
    return n ? `Speaker ${n}` : text;
  }
  return text;
}

function rebaseNode(edit: Json, stored: Json, refs: Json[], ctx: Ctx, names: Map<string, string>): Json {
  if (typeof edit === 'string') {
    // Untouched (identical to a resolved view the editor could have read): send the stored text.
    if (typeof stored === 'string' && refs.some((ref) => ref === edit)) return stored;
    return unrenderLeaf(edit, ctx, names);
  }
  if (Array.isArray(edit)) {
    // Items are matched by position only when the list shape is unchanged; otherwise every string
    // is treated as edited and only un-rendered.
    const aligned = Array.isArray(stored) && stored.length === edit.length;
    return edit.map((item, i) =>
      rebaseNode(
        item,
        aligned ? (stored as Json[])[i] : undefined,
        aligned ? refs.map((ref) => (Array.isArray(ref) && ref.length === edit.length ? ref[i] : undefined)) : [],
        ctx,
        names
      )
    );
  }
  if (isRecord(edit)) {
    const out: Record<string, Json> = {};
    for (const key of Object.keys(edit)) {
      out[key] = rebaseNode(
        edit[key],
        isRecord(stored) ? stored[key] : undefined,
        refs.map((ref) => (isRecord(ref) ? ref[key] : undefined)),
        { key, parent: edit },
        names
      );
    }
    return out;
  }
  // Numbers/booleans/null are never rendered: keep the caller's (e.g. `revision`, which drives the
  // server's lost-update guard, must stay the revision the editor actually read).
  return edit;
}

/**
 * Rebases an edited copy of the RESOLVED minutes onto the STORED (label-token) minutes: unchanged
 * strings take the stored value; edited prose keeps the reviewer's text with every rendered name /
 * "Vorbitorul N" / "Участник N" / "Speaker N" mapped back to its S<n> token, so a name the editor
 * pre-filled stays conditional on the confirmation and translation never receives it. A name that
 * rendered for several clusters is ambiguous and left as typed. `resolvedViews` are the resolved
 * renderings the editor may have started from (undefined entries are ignored).
 */
export function rebaseMinutesEdit(
  edited: MinutesOfMeeting,
  stored: MinutesOfMeeting,
  resolvedViews: Array<MinutesOfMeeting | undefined>
): MinutesOfMeeting {
  const refs = resolvedViews.filter((view): view is MinutesOfMeeting => view !== undefined);
  const seen = new Map<string, Set<string>>();
  for (const view of refs) collectRenderedNames(stored, view, seen);
  const names = new Map<string, string>();
  for (const [name, numbers] of seen) {
    if (numbers.size === 1) names.set(name, [...numbers][0]);
  }
  return rebaseNode(edited, stored, refs, { key: '', parent: null }, names) as MinutesOfMeeting;
}
