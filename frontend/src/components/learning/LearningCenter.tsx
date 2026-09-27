import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  Clock,
  Volume2,
  AlertTriangle,
  Play,
  RotateCcw,
  Sparkles,
  Loader2,
  Filter,
  Check,
  X,
  FileAudio,
} from 'lucide-react';
import { apiClient } from '../../api/client';
import { CorrectionEvent, LearningInboxResponse, EditKind } from '../../types';
import { useToast } from '../Toast';

interface LearningCenterProps {
  onBack?: () => void;
  onSelectMeeting?: (meetingId: string) => void;
}

export const LearningCenter: React.FC<LearningCenterProps> = ({ onBack, onSelectMeeting }) => {
  const { showToast } = useToast();
  const [inbox, setInbox] = useState<LearningInboxResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [activeAudioId, setActiveAudioId] = useState<string | null>(null);

  // Form states per event: eventId -> state
  const [formState, setFormState] = useState<
    Record<
      string,
      {
        verifiedAgainstAudio: boolean;
        trainingReuseAllowed: boolean;
        reviewerLabel: string;
        editKind: EditKind;
        isSubmitting: boolean;
        rejectReason?: string;
        showRejectPrompt?: boolean;
      }
    >
  >({});

  const loadCorrections = async () => {
    setIsLoading(true);
    try {
      const data = await apiClient.getLearningCorrections(
        undefined,
        statusFilter === 'all' ? undefined : statusFilter
      );
      setInbox(data);
    } catch (err: any) {
      showToast('Error', err.message || 'Failed to load learning corrections', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadCorrections();
  }, [statusFilter]);

  const getFormForEvent = (event: CorrectionEvent) => {
    return (
      formState[event.id] || {
        verifiedAgainstAudio: false, // Contract: NEVER precheck
        trainingReuseAllowed: false, // Contract: NEVER precheck
        reviewerLabel: event.reviewer_label || 'Clinical Reviewer',
        editKind: (event.edit_kind === 'editorial' ? 'transcription' : event.edit_kind) as EditKind,
        isSubmitting: false,
      }
    );
  };

  const updateFormForEvent = (eventId: string, updates: Partial<ReturnType<typeof getFormForEvent>>) => {
    setFormState((prev) => ({
      ...prev,
      [eventId]: {
        ...(prev[eventId] || {
          verifiedAgainstAudio: false,
          trainingReuseAllowed: false,
          reviewerLabel: 'Clinical Reviewer',
          editKind: 'transcription',
          isSubmitting: false,
        }),
        ...updates,
      },
    }));
  };

  const handleVerify = async (event: CorrectionEvent) => {
    const currentForm = getFormForEvent(event);
    if (!currentForm.verifiedAgainstAudio) {
      showToast('Audio Verification Required', 'You must listen to the audio interval and check the verification box.', 'error');
      return;
    }
    if (!currentForm.trainingReuseAllowed) {
      showToast('Consent Required', 'Explicit training reuse consent must be checked.', 'error');
      return;
    }
    if (!event.new_text.trim()) {
      showToast('Ineligible', 'Empty deletions cannot be verified as acoustic training labels.', 'error');
      return;
    }

    updateFormForEvent(event.id, { isSubmitting: true });
    try {
      await apiClient.verifyCorrection(event.id, {
        expected_revision: event.transcript_revision,
        audio_start: event.audio_start || 0,
        audio_end: event.audio_end || 0,
        edit_kind: currentForm.editKind,
        reviewer_label: currentForm.reviewerLabel,
        verified_against_audio: true,
        training_reuse_allowed: true,
      });
      showToast('Verified for Adaptation', `Correction verified by ${currentForm.reviewerLabel}.`);
      await loadCorrections();
    } catch (err: any) {
      showToast('Verification Failed', err.message || 'Could not verify correction.', 'error');
    } finally {
      updateFormForEvent(event.id, { isSubmitting: false });
    }
  };

  const handleReject = async (event: CorrectionEvent) => {
    const currentForm = getFormForEvent(event);
    const reason = currentForm.rejectReason?.trim() || 'Unsuitable for acoustic model training';

    updateFormForEvent(event.id, { isSubmitting: true });
    try {
      await apiClient.rejectCorrection(event.id, {
        reason,
        reviewer_label: currentForm.reviewerLabel,
      });
      showToast('Correction Rejected', 'Excluded from dataset generation.');
      await loadCorrections();
    } catch (err: any) {
      showToast('Rejection Failed', err.message || 'Could not reject correction.', 'error');
    } finally {
      updateFormForEvent(event.id, { isSubmitting: false, showRejectPrompt: false });
    }
  };

  const counts = inbox?.counts || {
    total_events: 0,
    unverified_events: 0,
    rejected_events: 0,
    distinct_verified_events: 0,
    distinct_verified_meetings: 0,
    distinct_verified_speakers: 0,
  };

  return (
    <div className="w-full space-y-6">
      {/* Header Banner */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center space-x-2 px-3 py-1 bg-purple-50 text-purple-800 border border-purple-200 rounded-full text-xs font-bold mb-2">
            <Sparkles className="w-3.5 h-3.5 text-purple-600" />
            <span>Dialect Adaptation &amp; Review Loop</span>
          </div>
          <h2 className="text-xl font-black text-slate-900">ASR Learning &amp; Verification Center</h2>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Controlled human-in-the-loop adaptation for Moldovan Romanian, Russian, and English clinical terms.
            Candidate counts represent distinct verified events and speakers; they do not imply model accuracy gains without held-out audio evaluation.
          </p>
        </div>

        {onBack && (
          <button
            onClick={onBack}
            className="px-4 py-2 text-xs font-bold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors self-start md:self-auto"
          >
            Back
          </button>
        )}
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Total Recorded</p>
          <p className="text-2xl font-black text-slate-800 mt-1">{counts.total_events}</p>
          <p className="text-[10px] text-slate-400 mt-0.5">Audit history events</p>
        </div>
        <div className="bg-white p-4 rounded-xl border border-amber-200 bg-amber-50/30 shadow-xs">
          <p className="text-[11px] font-semibold text-amber-700 uppercase tracking-wider">Pending Verification</p>
          <p className="text-2xl font-black text-amber-800 mt-1">{counts.unverified_events}</p>
          <p className="text-[10px] text-amber-600 mt-0.5">Awaiting audio listen</p>
        </div>
        <div className="bg-white p-4 rounded-xl border border-emerald-200 bg-emerald-50/30 shadow-xs">
          <p className="text-[11px] font-semibold text-emerald-700 uppercase tracking-wider">Verified Pairs</p>
          <p className="text-2xl font-black text-emerald-800 mt-1">{counts.distinct_verified_events}</p>
          <p className="text-[10px] text-emerald-600 mt-0.5">
            {counts.distinct_verified_meetings} mtgs · {counts.distinct_verified_speakers} spks
          </p>
        </div>
        <div className="bg-white p-4 rounded-xl border border-blue-200 bg-blue-50/30 shadow-xs">
          <p className="text-[11px] font-semibold text-blue-700 uppercase tracking-wider">Eligible Duration</p>
          <p className="text-2xl font-black text-blue-800 mt-1">
            {Math.floor((inbox?.eligible_audio_duration_seconds || 0) / 60)}m{' '}
            {Math.round((inbox?.eligible_audio_duration_seconds || 0) % 60)}s
          </p>
          <p className="text-[10px] text-blue-600 mt-0.5">Verified audio length</p>
        </div>
      </div>

      {/* Filter and Table Section */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 bg-slate-50/50">
          <div className="flex items-center space-x-2">
            <Filter className="w-4 h-4 text-slate-500" />
            <span className="text-xs font-bold text-slate-700">Filter Status:</span>
            <div className="flex items-center space-x-1">
              {(['all', 'unverified', 'verified', 'rejected'] as const).map((st) => (
                <button
                  key={st}
                  onClick={() => setStatusFilter(st)}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold capitalize transition-all ${
                    statusFilter === st
                      ? 'bg-medpark-500 text-white shadow-xs'
                      : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200'
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={loadCorrections}
            disabled={isLoading}
            className="inline-flex items-center space-x-1 px-3 py-1 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-bold text-slate-700 transition-colors"
          >
            <RotateCcw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Correction Events List */}
        <div className="divide-y divide-slate-200">
          {isLoading ? (
            <div className="p-12 text-center text-slate-400">
              <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-medpark-500" />
              <p className="text-xs font-medium">Loading correction catalog...</p>
            </div>
          ) : !inbox?.corrections || inbox.corrections.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <p className="text-sm font-semibold text-slate-600">No corrections found</p>
              <p className="text-xs mt-1">Reviewers can amend transcript segments to populate this learning inbox.</p>
            </div>
          ) : (
            inbox.corrections.map((ev) => {
              const form = getFormForEvent(ev);
              return (
                <div key={ev.id} className="p-5 space-y-4 hover:bg-slate-50/50 transition-colors">
                  {/* Row Top: Meta & Badges */}
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center space-x-2">
                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                          ev.verification_status === 'verified'
                            ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                            : ev.verification_status === 'rejected'
                            ? 'bg-rose-100 text-rose-800 border border-rose-300'
                            : 'bg-amber-100 text-amber-800 border border-amber-300'
                        }`}
                      >
                        {ev.verification_status}
                      </span>
                      <span className="text-xs font-mono font-semibold text-slate-600">
                        Rev.{ev.transcript_revision}
                      </span>
                      <span className="text-xs text-slate-400">·</span>
                      <span className="text-xs text-slate-500 font-mono">
                        [{ev.audio_start ? ev.audio_start.toFixed(1) : '0.0'}s –{' '}
                        {ev.audio_end ? ev.audio_end.toFixed(1) : '0.0'}s]
                      </span>
                      {ev.speaker_cluster && (
                        <span className="text-[11px] font-medium text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
                          {ev.speaker_cluster}
                        </span>
                      )}
                    </div>

                    <div className="text-[11px] text-slate-400">
                      Edited {new Date(ev.created_at).toLocaleString()}
                      {ev.reviewer_label && ` by ${ev.reviewer_label}`}
                    </div>
                  </div>

                  {/* Text Comparison Box */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs bg-slate-50 p-3.5 rounded-xl border border-slate-200">
                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                        <span>Original Recognition</span>
                        <span className="text-[10px] lowercase font-normal font-mono bg-slate-200 px-1 rounded">
                          {ev.raw_text_origin || 'decoder'}
                        </span>
                      </div>
                      <p className="font-mono text-slate-700 bg-white p-2 rounded border border-slate-200 min-h-[44px]">
                        {ev.raw_text || ev.previous_text}
                      </p>
                      {ev.normalized_text && (
                        <p className="text-[11px] text-sky-700 mt-1">
                          <span className="font-semibold">Normalized:</span> {ev.normalized_text}
                        </p>
                      )}
                    </div>

                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-[11px] font-bold text-emerald-700 uppercase tracking-wider">
                        <span>Reviewer Correction</span>
                        <span className="text-[10px] lowercase font-normal bg-emerald-50 text-emerald-700 border border-emerald-200 px-1 rounded">
                          {ev.edit_kind}
                        </span>
                      </div>
                      <p className="font-sans text-slate-900 bg-white p-2 rounded border border-emerald-300 min-h-[44px] font-medium">
                        {ev.new_text === '' ? (
                          <span className="italic text-slate-400">[Removed / Deleted]</span>
                        ) : (
                          ev.new_text
                        )}
                      </p>
                    </div>
                  </div>

                  {/* Verification & Action Form */}
                  {ev.verification_status !== 'verified' ? (
                    <div className="pt-2 border-t border-slate-100 flex flex-col md:flex-row md:items-center justify-between gap-4">
                      <div className="space-y-1.5">
                        <label className="flex items-center space-x-2 text-xs text-slate-700 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={form.verifiedAgainstAudio}
                            onChange={(e) =>
                              updateFormForEvent(ev.id, { verifiedAgainstAudio: e.target.checked })
                            }
                            className="rounded border-slate-300 text-medpark-600 focus:ring-medpark-500"
                          />
                          <span>I have listened to this audio interval and verified this verbatim transcription</span>
                        </label>

                        <label className="flex items-center space-x-2 text-xs text-slate-700 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={form.trainingReuseAllowed}
                            onChange={(e) =>
                              updateFormForEvent(ev.id, { trainingReuseAllowed: e.target.checked })
                            }
                            className="rounded border-slate-300 text-medpark-600 focus:ring-medpark-500"
                          />
                          <span>Explicit consent: include this audio interval in offline adaptation dataset</span>
                        </label>
                      </div>

                      <div className="flex items-center space-x-2 self-end md:self-auto">
                        <input
                          type="text"
                          value={form.reviewerLabel}
                          onChange={(e) => updateFormForEvent(ev.id, { reviewerLabel: e.target.value })}
                          placeholder="Reviewer Name"
                          className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20 w-36"
                        />

                        <button
                          onClick={() => handleReject(ev)}
                          disabled={form.isSubmitting}
                          className="px-3 py-1.5 text-xs font-bold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-lg transition-colors disabled:opacity-50"
                        >
                          Reject
                        </button>

                        <button
                          onClick={() => handleVerify(ev)}
                          disabled={
                            form.isSubmitting ||
                            !form.verifiedAgainstAudio ||
                            !form.trainingReuseAllowed ||
                            !ev.new_text.trim()
                          }
                          className="inline-flex items-center space-x-1.5 px-4 py-1.5 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-500 rounded-lg transition-all shadow-xs disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed"
                        >
                          {form.isSubmitting ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Check className="w-3.5 h-3.5" />
                          )}
                          <span>Verify for Training</span>
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-600">
                      <div className="flex items-center space-x-2 text-emerald-800">
                        <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                        <span>
                          Verified against audio coordinates by <strong>{ev.verified_by}</strong> on{' '}
                          {ev.verified_at ? new Date(ev.verified_at).toLocaleDateString() : 'recent'}
                        </span>
                      </div>

                      <button
                        onClick={() => handleReject(ev)}
                        className="text-[11px] text-slate-500 hover:text-rose-600 underline"
                      >
                        Revoke Consent
                      </button>
                    </div>
                  )}

                  {ev.verification_status === 'rejected' && ev.rejection_reason && (
                    <div className="pt-2 border-t border-slate-100 text-xs text-rose-700 flex items-center space-x-1.5">
                      <XCircle className="w-4 h-4 text-rose-500 flex-shrink-0" />
                      <span>Rejection reason: {ev.rejection_reason}</span>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
