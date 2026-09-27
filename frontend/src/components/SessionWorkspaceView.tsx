import React, { useState } from 'react';
import {
  Meeting,
  Transcript,
  MinutesOfMeeting,
} from '../types';
import { apiClient } from '../api/client';
import { WaveformPlayer, WaveformPlayerRef } from './WaveformPlayer';
import { TranscriptViewer } from './TranscriptViewer';
import { DecisionsTable } from './DecisionsTable';
import { ActionItemsTable } from './ActionItemsTable';
import { RisksQuestionsTable } from './RisksQuestionsTable';
import { SpeakerAssignmentCard } from './voice/SpeakerAssignmentCard';
import {
  FileText,
  Clock,
  CheckCircle2,
  AlertCircle,
  FileDown,
  Rocket,
  Shield,
  Layers,
  Sparkles,
  Loader2,
  Calendar,
  Users,
  Edit3,
  Save,
  XCircle,
  BookmarkCheck,
  Trash2,
  Copy,
  ChevronLeft,
  ChevronDown,
  Plus,
  Globe,
  Archive,
  X,
} from 'lucide-react';

interface SessionWorkspaceViewProps {
  meetings: Meeting[];
  selectedMeeting: Meeting | null;
  onSelectMeeting: (id: string) => void;
  onBackToDashboard: () => void;
  onBackToVault?: () => void;
  minutes: MinutesOfMeeting | null;
  transcript: Transcript | null;
  isProcessing: boolean;
  pipelineProgress: number;
  pipelineStage: string;
  stageDetail: string;
  activeTab: 'minutes' | 'transcript' | 'speakers';
  setActiveTab: (tab: 'minutes' | 'transcript' | 'speakers') => void;
  /** Speaker identification tab: shown only while /ready reports voice identification as enabled. */
  showSpeakersTab?: boolean;
  /** Content of the Speakers tab (the confirmation panel); rendered when activeTab === 'speakers'. */
  speakersPanel?: React.ReactNode;
  playbackTime: number;
  setPlaybackTime: (time: number) => void;
  playbackBucketRef: React.MutableRefObject<number>;
  waveformRef: React.RefObject<WaveformPlayerRef>;
  onCopyFullMoM: () => void;
  onDeleteMeeting: (meeting: Meeting) => void;
  onOpenApproval: () => void;
  onOpenOutbox: () => void;
  onOpenIntake: () => void;
  isEditingSummary: boolean;
  setIsEditingSummary: (v: boolean) => void;
  summaryRoEdit: string;
  setSummaryRoEdit: (v: string) => void;
  summaryRuEdit: string;
  setSummaryRuEdit: (v: string) => void;
  summaryEnEdit: string;
  setSummaryEnEdit: (v: string) => void;
  isSavingMinutes: boolean;
  onSaveSummary: () => void;
  onUpdateSegment: (segmentId: string, text: string) => Promise<void>;
  onSeekAudio: (time: number) => void;
  onMinutesUpdated?: (minutes: MinutesOfMeeting) => void;
  onAttributionChanged?: () => void;
}

const PIPELINE_STAGES: { key: string; label: string }[] = [
  { key: 'preprocessing', label: 'Audio preprocessing' },
  { key: 'transcribing', label: 'Transcription' },
  { key: 'diarizing', label: 'Speaker diarization' },
  { key: 'extracting', label: 'Minutes extraction' },
  { key: 'generating_docs', label: 'Document generation' },
];

const isFallbackExtraction = (modelVersion?: string): boolean =>
  (modelVersion || '').toLowerCase().includes('fallback');

export const SessionWorkspaceView: React.FC<SessionWorkspaceViewProps> = ({
  meetings,
  selectedMeeting,
  onSelectMeeting,
  onBackToDashboard,
  onBackToVault,
  minutes,
  transcript,
  isProcessing,
  pipelineProgress,
  pipelineStage,
  stageDetail,
  activeTab,
  setActiveTab,
  showSpeakersTab = false,
  speakersPanel = null,
  playbackTime,
  setPlaybackTime,
  playbackBucketRef,
  waveformRef,
  onCopyFullMoM,
  onDeleteMeeting,
  onOpenApproval,
  onOpenOutbox,
  onOpenIntake,
  isEditingSummary,
  setIsEditingSummary,
  summaryRoEdit,
  setSummaryRoEdit,
  summaryRuEdit,
  setSummaryRuEdit,
  summaryEnEdit,
  setSummaryEnEdit,
  isSavingMinutes,
  onSaveSummary,
  onUpdateSegment,
  onSeekAudio,
  onMinutesUpdated,
  onAttributionChanged,
}) => {
  const [momLanguage, setMomLanguage] = useState<'ro' | 'ru' | 'en' | 'all'>('ro');
  const [isTranslating, setIsTranslating] = useState<'ru' | 'en' | null>(null);
  const [dismissedRevisionKey, setDismissedRevisionKey] = useState<string | null>(null);
  const [isRefreshingMinutes, setIsRefreshingMinutes] = useState(false);
  const [refreshMinutesError, setRefreshMinutesError] = useState<string | null>(null);

  const handleRefreshMinutes = async () => {
    if (!selectedMeeting) return;
    setIsRefreshingMinutes(true);
    setRefreshMinutesError(null);
    try {
      const updated = await apiClient.refreshMinutes(selectedMeeting.id);
      if (onMinutesUpdated) {
        onMinutesUpdated(updated);
      }
    } catch (err) {
      console.error('Failed to refresh minutes:', err);
      setRefreshMinutesError(err instanceof Error ? err.message : 'Failed to refresh minutes');
    } finally {
      setIsRefreshingMinutes(false);
    }
  };

  const handleLanguageChange = async (newLang: 'ro' | 'ru' | 'en' | 'all') => {
    setMomLanguage(newLang);
    if (newLang !== 'ru' && newLang !== 'en') {
      return;
    }
    if (!minutes || !selectedMeeting) {
      return;
    }

    const hasTranslation =
      newLang === 'ru'
        ? Boolean(minutes.agenda_topics_ru && minutes.agenda_topics_ru.length > 0) ||
          Boolean(minutes.decisions?.some((d) => d.decision_ru)) ||
          Boolean(minutes.action_items?.some((a) => a.task_ru))
        : Boolean(minutes.agenda_topics_en && minutes.agenda_topics_en.length > 0) ||
          Boolean(minutes.decisions?.some((d) => d.decision_en)) ||
          Boolean(minutes.action_items?.some((a) => a.task_en));

    if (!hasTranslation && !isTranslating) {
      try {
        setIsTranslating(newLang);
        const updated = await apiClient.translateMinutes(selectedMeeting.id, newLang, false);
        if (onMinutesUpdated) {
          onMinutesUpdated(updated);
        }
      } catch (err) {
        console.error(`Failed to translate minutes to ${newLang}:`, err);
      } finally {
        setIsTranslating(null);
      }
    }
  };

  const failedChunkCount = minutes?.failed_chunks?.length ?? 0;
  const showReviewFlags = Boolean(
    minutes && (minutes.is_degraded || minutes.needs_name_review || failedChunkCount > 0)
  );
  const currentRevisionKey = selectedMeeting && minutes ? `${selectedMeeting.id}-${minutes.revision}` : null;
  const isFlagsDismissed = dismissedRevisionKey !== null && dismissedRevisionKey === currentRevisionKey;

  const getReviewFlagMessage = () => {
    if (!minutes) return '';
    if (minutes.is_degraded) {
      return 'Heuristic draft (local LLM unavailable) — re-run pipeline before sign-off.';
    }
    const parts: string[] = [];
    if (minutes.needs_name_review) {
      parts.push('Name review needed: an action owner or proper noun is not on the attendee roster.');
    }
    if (failedChunkCount > 0) {
      parts.push(`${failedChunkCount} transcript fragment${failedChunkCount === 1 ? '' : 's'} failed extraction.`);
    }
    return parts.join(' ');
  };

  if (!selectedMeeting) {
    return (
      <div className="max-w-4xl mx-auto p-12 bg-white rounded-3xl border border-slate-200 text-center space-y-4 shadow-xs">
        <Layers className="w-12 h-12 text-slate-300 mx-auto" />
        <h2 className="text-lg font-bold text-slate-800">No Session Selected</h2>
        <p className="text-xs text-slate-500 max-w-sm mx-auto">
          Please select a meeting from the dashboard or create a new session to open the workspace.
        </p>
        <button
          onClick={onBackToDashboard}
          className="inline-flex items-center space-x-1.5 px-4 py-2 bg-medpark-500 text-white text-xs font-bold rounded-xl hover:bg-medpark-600 transition-colors shadow-xs"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Go to Dashboard</span>
        </button>
      </div>
    );
  }

  const activeStageIndex = PIPELINE_STAGES.findIndex((s) => s.key === pipelineStage);
  const activeStageLabel =
    activeStageIndex >= 0 ? PIPELINE_STAGES[activeStageIndex].label : 'Starting pipeline';

  const signOffBlockedReason =
    selectedMeeting.processing_status === 'failed'
      ? 'The pipeline failed. Re-run processing before sign-off.'
      : selectedMeeting.processing_status !== 'completed'
        ? selectedMeeting.original_audio_path
          ? 'Waiting for the pipeline to finish processing this recording.'
          : 'No audio has been processed for this meeting yet.'
        : !minutes
          ? 'No minutes were generated, so there is nothing to sign.'
          : minutes.needs_transcript_review
            ? 'Stale minutes: refresh before sign-off'
            : null;

  return (
    <div className="w-full space-y-6">
      {/* Top Workspace Bar: Navigation & Quick Session Switcher */}
      <div className="bg-white p-4 rounded-2xl border border-slate-200/90 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center space-x-2">
          {onBackToVault && (
            <button
              onClick={onBackToVault}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-medpark-700 bg-medpark-50 hover:bg-medpark-100 border border-medpark-200 transition-colors shadow-xs"
              title="Return to Meeting Intelligence Vault"
            >
              <Archive className="w-3.5 h-3.5 text-medpark-600" />
              <span>Vault</span>
            </button>
          )}

          <button
            onClick={onBackToDashboard}
            className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-xl text-xs font-semibold text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors"
            title="Return to Dashboard view"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            <span>Dashboard</span>
          </button>

          <span className="text-slate-300 hidden sm:inline">|</span>

          {/* Meeting Quick Selector Dropdown */}
          <div className="relative flex-1 min-w-[240px]">
            <select
              value={selectedMeeting.id}
              onChange={(e) => onSelectMeeting(e.target.value)}
              aria-label="Switch active meeting"
              className="w-full text-xs font-bold text-slate-800 bg-slate-50 border border-slate-300 rounded-xl px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-medpark-500/20 cursor-pointer"
            >
              {meetings.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.title} ({new Date(m.scheduled_at).toLocaleDateString()}) - {m.review_status}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <span className="text-[11px] font-mono text-slate-400">
            ID: {selectedMeeting.id.slice(0, 8)}
          </span>
          <button
            onClick={onOpenIntake}
            className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-xl text-xs font-bold text-medpark-700 bg-medpark-50 hover:bg-medpark-100 border border-medpark-200 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Session</span>
          </button>
        </div>
      </div>

      {/* Stale Minutes Alert Banner */}
      {minutes?.needs_transcript_review && (
        <div
          role="alert"
          className="bg-amber-50 border-2 border-amber-400 rounded-2xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 text-amber-900 shadow-xs"
        >
          <div className="flex items-start space-x-3">
            <AlertCircle className="w-5 h-5 text-amber-600 mt-0.5 flex-shrink-0" />
            <div>
              <p className="font-bold text-xs text-amber-950">
                Transcript was modified after minutes were generated. Minutes must be refreshed before sign-off.
              </p>
              <p className="text-[11px] text-amber-800 mt-0.5">
                New transcript revisions have invalidated the current draft summary and action items. Refreshing will re-extract minutes based on the latest verified transcript.
              </p>
              {refreshMinutesError && (
                <p className="text-xs font-semibold text-rose-600 mt-1">
                  {refreshMinutesError}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={handleRefreshMinutes}
            disabled={isRefreshingMinutes}
            className="inline-flex items-center space-x-1.5 px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-bold text-xs rounded-xl shadow-xs transition-colors flex-shrink-0 disabled:opacity-50"
          >
            {isRefreshingMinutes ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Refreshing...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5" />
                <span>Refresh Minutes</span>
              </>
            )}
          </button>
        </div>
      )}

      {/* Review Flags Banner - Compact Single Line */}
      {showReviewFlags && !isFlagsDismissed && (
        <div
          role="alert"
          className={`px-4 py-2.5 rounded-xl border flex items-center justify-between gap-3 text-xs shadow-xs transition-all ${
            minutes?.is_degraded
              ? 'bg-rose-50 border-rose-200 text-rose-800'
              : 'bg-amber-50 border-amber-200 text-amber-900'
          }`}
        >
          <div className="flex items-center space-x-2.5 min-w-0 flex-1">
            <AlertCircle
              className={`w-4 h-4 flex-shrink-0 ${minutes?.is_degraded ? 'text-rose-600' : 'text-amber-600'}`}
              aria-hidden="true"
            />
            <span
              className={`font-bold text-[10px] uppercase tracking-wider px-2 py-0.5 rounded flex-shrink-0 ${
                minutes?.is_degraded ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-900'
              }`}
            >
              {minutes?.is_degraded ? 'Degraded Draft' : 'Review Flag'}
            </span>
            <span className="font-medium truncate">
              {getReviewFlagMessage()}
            </span>
            {minutes?.model_version && (
              <span className="hidden lg:inline-flex items-center font-mono text-[10px] text-slate-500 bg-white/70 px-2 py-0.5 rounded border border-slate-200/60 flex-shrink-0 ml-auto">
                Model: {minutes.model_version}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => currentRevisionKey && setDismissedRevisionKey(currentRevisionKey)}
            className="text-slate-400 hover:text-slate-700 p-1 rounded-md transition-colors flex-shrink-0"
            title="Dismiss review notice"
            aria-label="Dismiss review notice"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Live Processing Banner */}
      {isProcessing && (
        <section
          aria-label="Pipeline progress"
          className="bg-gradient-to-r from-blue-600 to-medpark-600 text-white p-5 rounded-2xl shadow-sm space-y-3"
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center space-x-2.5 min-w-0">
              <Loader2 className="w-5 h-5 motion-safe:animate-spin flex-shrink-0" aria-hidden="true" />
              <h3 className="font-bold text-sm tracking-wide truncate">
                Medora Intelligence Pipeline (100% Air-Gapped)
              </h3>
            </div>
            <span className="font-mono text-sm font-bold bg-white/20 px-2.5 py-0.5 rounded-full tabular-nums flex-shrink-0">
              {pipelineProgress}%
            </span>
          </div>

          <div
            role="progressbar"
            aria-label="Pipeline progress"
            aria-valuenow={Math.round(pipelineProgress)}
            aria-valuemin={0}
            aria-valuemax={100}
            className="w-full bg-black/20 rounded-full h-2 overflow-hidden"
          >
            <div
              className="bg-white h-2 rounded-full transition-all duration-300"
              style={{ width: `${pipelineProgress}%` }}
            />
          </div>

          <ol className="flex flex-wrap items-center gap-1.5">
            {PIPELINE_STAGES.map((stage, idx) => {
              const isDone = activeStageIndex > idx;
              const isCurrent = activeStageIndex === idx;
              return (
                <li
                  key={stage.key}
                  className={`inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide border ${
                    isCurrent
                      ? 'bg-white text-medpark-700 border-white shadow-xs'
                      : isDone
                        ? 'bg-white/20 text-white border-white/30'
                        : 'text-blue-100/80 border-white/20'
                  }`}
                >
                  {isDone ? (
                    <CheckCircle2 className="w-3 h-3" aria-hidden="true" />
                  ) : (
                    <span className="w-3 text-center tabular-nums" aria-hidden="true">
                      {idx + 1}
                    </span>
                  )}
                  <span>{stage.label}</span>
                </li>
              );
            })}
          </ol>

          <p aria-live="polite" className="text-xs font-medium text-blue-50">
            <span className="font-bold">
              Stage {activeStageIndex >= 0 ? activeStageIndex + 1 : 1} of {PIPELINE_STAGES.length}:{' '}
              {activeStageLabel}
            </span>
            {stageDetail && (
              <>
                <span className="px-1.5 text-blue-200" aria-hidden="true">/</span>
                <span lang="ro" className="text-blue-100">{stageDetail}</span>
              </>
            )}
          </p>
        </section>
      )}

      {/* Meeting Meta Card Header */}
      <div className="bg-gradient-to-r from-slate-900 via-medpark-900 to-slate-900 text-white rounded-3xl p-6 sm:p-7 shadow-sm relative overflow-hidden border border-white/10 flex flex-col lg:flex-row lg:items-start justify-between gap-5">
        {/* Subtle ambient decorative glow */}
        <div className="absolute -right-20 -top-20 w-80 h-80 bg-medpark-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="space-y-2 min-w-0 relative z-10">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="text-xl sm:text-2xl font-black text-white tracking-tight">
              {selectedMeeting.title}
            </h2>
            <span className="text-xs font-bold uppercase px-2.5 py-0.5 rounded-lg bg-white/10 text-white border border-white/15 backdrop-blur-xs">
              {selectedMeeting.meeting_type}
            </span>

            <span
              className={`inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-lg text-xs font-bold border backdrop-blur-xs ${
                selectedMeeting.workflow_mode === 'auto_pilot'
                  ? 'bg-blue-500/20 text-blue-200 border-blue-400/30'
                  : 'bg-emerald-500/20 text-emerald-200 border-emerald-400/30'
              }`}
            >
              {selectedMeeting.workflow_mode === 'auto_pilot' ? (
                <>
                  <Rocket className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Auto-Pilot Processing</span>
                </>
              ) : (
                <>
                  <Shield className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Supervised (Clinical Gate)</span>
                </>
              )}
            </span>

            {selectedMeeting.review_status === 'delivered' && (
              <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-lg text-xs font-bold bg-emerald-500/25 text-emerald-300 border border-emerald-400/40">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" aria-hidden="true" />
                <span>Delivered via Email</span>
              </span>
            )}

            {selectedMeeting.review_status === 'approved' && (
              <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-lg text-xs font-bold bg-amber-500/25 text-amber-300 border border-amber-400/40">
                <AlertCircle className="w-3.5 h-3.5 text-amber-400" aria-hidden="true" />
                <span>Signed - Not Delivered</span>
              </span>
            )}

            {selectedMeeting.processing_status === 'failed' && (
              <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-lg text-xs font-bold bg-rose-500/25 text-rose-300 border border-rose-400/40">
                <AlertCircle className="w-3.5 h-3.5 text-rose-400" aria-hidden="true" />
                <span>Pipeline Failed</span>
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-300 font-medium pt-1">
            <span className="flex items-center space-x-1.5">
              <Calendar className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
              <span>{new Date(selectedMeeting.scheduled_at).toLocaleString()}</span>
            </span>
            <span className="flex items-center space-x-1.5">
              <Clock className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
              <span>
                Audio:{' '}
                <span className="font-mono tabular-nums text-white">
                  {selectedMeeting.audio_duration_seconds.toFixed(1)}s
                </span>
              </span>
            </span>
            <span className="flex items-center space-x-1.5">
              <Users className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
              <span>
                <span className="tabular-nums text-white font-bold">{selectedMeeting.attendees.length}</span> participants
              </span>
            </span>
            {selectedMeeting.processing_time_seconds > 0 && (
              <span className="flex items-center space-x-1.5 font-mono tabular-nums text-emerald-300 font-bold bg-emerald-500/10 px-2 py-0.5 rounded-md border border-emerald-500/20">
                <Sparkles className="w-3.5 h-3.5 text-emerald-400" aria-hidden="true" />
                <span>Pipeline: {selectedMeeting.processing_time_seconds}s</span>
              </span>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col gap-2.5 lg:items-end flex-shrink-0 relative z-10">
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <button
              onClick={onOpenOutbox}
              className="px-3.5 py-2 bg-white/10 hover:bg-white/20 text-white border border-white/15 text-xs font-bold rounded-xl transition-all backdrop-blur-xs focus-visible:ring-2 focus-visible:ring-medpark-400"
            >
              Email Outbox
            </button>
            {minutes && (
              <button
                onClick={onCopyFullMoM}
                className="inline-flex items-center space-x-1.5 px-3.5 py-2 bg-white/10 hover:bg-white/20 text-white border border-white/15 text-xs font-bold rounded-xl transition-all backdrop-blur-xs focus-visible:ring-2 focus-visible:ring-medpark-400"
                title="Copy executive summary, decisions, and action items as Markdown"
              >
                <Copy className="w-3.5 h-3.5 text-slate-300" />
                <span>Copy Full MoM</span>
              </button>
            )}

            {minutes && (
              <>
                <a
                  href={apiClient.getPdfDownloadUrl(selectedMeeting.id)}
                  download
                  className="inline-flex items-center space-x-1.5 px-3 py-2 bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-400/30 text-xs font-bold rounded-xl transition-all backdrop-blur-xs"
                  title="Download official PDF report"
                >
                  <FileDown className="w-3.5 h-3.5 text-rose-400" />
                  <span>PDF</span>
                </a>

                <a
                  href={apiClient.getDocxDownloadUrl(selectedMeeting.id)}
                  download
                  className="inline-flex items-center space-x-1.5 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 text-blue-200 border border-blue-400/30 text-xs font-bold rounded-xl transition-all backdrop-blur-xs"
                  title="Download official Word DOCX report"
                >
                  <FileDown className="w-3.5 h-3.5 text-blue-400" />
                  <span>DOCX</span>
                </a>
              </>
            )}

            <button
              onClick={() => onDeleteMeeting(selectedMeeting)}
              className="p-2 text-slate-400 hover:text-rose-300 hover:bg-rose-500/20 rounded-xl transition-colors border border-white/10"
              title="Delete meeting record"
              aria-label="Delete meeting record"
            >
              <Trash2 className="w-4 h-4" />
            </button>

            {selectedMeeting.workflow_mode === 'supervised' &&
              selectedMeeting.review_status !== 'delivered' && (
                <>
                  <span className="hidden sm:block w-px h-7 bg-white/20" aria-hidden="true" />
                  <button
                    onClick={onOpenApproval}
                    disabled={signOffBlockedReason !== null}
                    title={signOffBlockedReason || 'Sign off and dispatch the official minutes'}
                    className="inline-flex items-center space-x-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-xl shadow-md transition-all disabled:bg-white/10 disabled:text-slate-400 disabled:border disabled:border-white/10 disabled:cursor-not-allowed"
                  >
                    <Shield className="w-4 h-4" />
                    <span>Sign &amp; Dispatch</span>
                  </button>
                </>
              )}
          </div>

          {selectedMeeting.workflow_mode === 'supervised' &&
            selectedMeeting.review_status !== 'delivered' &&
            signOffBlockedReason && (
              <p className="text-[11px] font-medium text-slate-300 lg:text-right max-w-xs">
                Sign &amp; Dispatch unavailable: {signOffBlockedReason}
              </p>
            )}
        </div>
      </div>

      {/* Audio Waveform Player */}
      {selectedMeeting.original_audio_path && (
        <WaveformPlayer
          ref={waveformRef}
          audioUrl={apiClient.getAudioStreamUrl(selectedMeeting.id)}
          onTimeUpdate={(t) => {
            const bucket = Math.floor(t * 4);
            if (bucket === playbackBucketRef.current) return;
            playbackBucketRef.current = bucket;
            setPlaybackTime(t);
          }}
        />
      )}

      {/* EU AI Act Article 50 & 14 AI Transparency & Human Oversight Notice Banner */}
      <div className="bg-slate-50/80 border border-slate-200 rounded-2xl p-3.5 shadow-xs flex items-start space-x-3 text-xs text-slate-700">
        <div className="w-7 h-7 rounded-lg bg-blue-100/80 text-blue-700 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Shield className="w-4 h-4" aria-hidden="true" />
        </div>
        <div className="flex-1 min-w-0 space-y-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-bold text-slate-900 text-xs">
              Notificare privind Asistența AI (EU AI Act Art. 50 &amp; Art. 14)
            </span>
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
              Draft Asistat AI • Supraveghere Umană Obligatorie
            </span>
          </div>
          <p className="text-[11px] text-slate-600 leading-relaxed">
            Transcrierile, sinteza ședinței și sarcinile sunt extrase asistat de modelele Medora AI locale. Deciziile și atribuirile de persoane sunt preliminare și necesită revizuire și asumare umană formală înainte de dispecerizarea oficială.
          </p>
        </div>
      </div>

      {/* Tabs Navigation */}
      <div role="tablist" aria-label="Meeting workspace tabs" className="border-b border-slate-200 flex space-x-6">
        <button
          role="tab"
          id="tab-minutes"
          aria-selected={activeTab === 'minutes'}
          onClick={() => setActiveTab('minutes')}
          title="Official Minutes (1)"
          className={`pb-3 text-sm font-bold flex items-center space-x-2 border-b-2 transition-colors ${
            activeTab === 'minutes'
              ? 'border-medpark-500 text-medpark-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <FileText className="w-4 h-4" />
          <span>Official Minutes (MoM)</span>
        </button>

        <button
          role="tab"
          id="tab-transcript"
          aria-selected={activeTab === 'transcript'}
          onClick={() => setActiveTab('transcript')}
          title="Transcript (2)"
          className={`pb-3 text-sm font-bold flex items-center space-x-2 border-b-2 transition-colors ${
            activeTab === 'transcript'
              ? 'border-medpark-500 text-medpark-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Layers className="w-4 h-4" />
          <span>{showSpeakersTab ? 'Multilingual Transcript' : 'Multilingual Transcript & Speakers'}</span>
          {transcript && (
            <span className="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-bold tabular-nums">
              {transcript.segments.length}
            </span>
          )}
        </button>

        {showSpeakersTab && (
          <button
            role="tab"
            id="tab-speakers"
            aria-selected={activeTab === 'speakers'}
            aria-controls="panel-speakers"
            onClick={() => setActiveTab('speakers')}
            title="Speakers (3)"
            className={`pb-3 text-sm font-bold flex items-center space-x-2 border-b-2 transition-colors ${
              activeTab === 'speakers'
                ? 'border-medpark-500 text-medpark-600'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <Users className="w-4 h-4" aria-hidden="true" />
            <span>Speakers</span>
          </button>
        )}
      </div>

      {/* Tab 3: Speaker identification (names reach the document only after reviewer confirmation) */}
      {activeTab === 'speakers' && showSpeakersTab && (
        <div role="tabpanel" id="panel-speakers" aria-labelledby="tab-speakers">
          {speakersPanel}
        </div>
      )}

      {/* Tab 1: Minutes Content */}
      {activeTab === 'minutes' && (
        <div role="tabpanel" id="panel-minutes" className="space-y-6">
          {selectedMeeting && (
            <SpeakerAssignmentCard
              meetingId={selectedMeeting.id}
              revision={minutes?.revision ?? null}
              attendees={selectedMeeting.attendees}
              onAttributionChanged={onAttributionChanged}
            />
          )}

          {minutes ? (
            <>
              {/* MoM Language Switcher Bar */}
              <div className="bg-white rounded-2xl border border-slate-200 p-3.5 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
                <div className="flex items-center space-x-2.5">
                  <div className="w-8 h-8 rounded-lg bg-medpark-50 text-medpark-600 flex items-center justify-center flex-shrink-0">
                    <Globe className="w-4 h-4" />
                  </div>
                  <div>
                    <span className="text-xs font-bold text-slate-900">
                      {momLanguage === 'ro'
                        ? 'Limba Proces-Verbal'
                        : momLanguage === 'ru'
                        ? 'Язык протокола'
                        : momLanguage === 'en'
                        ? 'Minutes Language'
                        : 'Limba Proces-Verbal (MoM)'}
                    </span>
                    <p className="text-[11px] text-slate-500">
                      {momLanguage === 'ro'
                        ? 'Afișare proces-verbal oficial în limba Română'
                        : momLanguage === 'ru'
                        ? 'Отображение официального протокола на русском языке'
                        : momLanguage === 'en'
                        ? 'Displaying official minutes in English'
                        : 'Afișare comparativă simultană a celor 3 limbi'}
                    </p>
                  </div>
                </div>

                <div
                  className="inline-flex p-1 bg-slate-100 rounded-xl space-x-1 self-start md:self-auto overflow-x-auto max-w-full"
                  role="radiogroup"
                  aria-label="MoM Language View"
                >
                  <button
                    onClick={() => handleLanguageChange('ro')}
                    role="radio"
                    aria-checked={momLanguage === 'ro'}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all whitespace-nowrap flex items-center space-x-1.5 ${
                      momLanguage === 'ro'
                        ? 'bg-white text-medpark-700 shadow-xs'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <span>🇲🇩</span>
                    <span>Română (RO)</span>
                  </button>
                  <button
                    onClick={() => handleLanguageChange('ru')}
                    role="radio"
                    aria-checked={momLanguage === 'ru'}
                    disabled={isTranslating !== null}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all whitespace-nowrap flex items-center space-x-1.5 ${
                      momLanguage === 'ru'
                        ? 'bg-white text-medpark-700 shadow-xs'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    {isTranslating === 'ru' ? (
                      <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin text-medpark-600" />
                    ) : (
                      <span>🇷🇺</span>
                    )}
                    <span>{isTranslating === 'ru' ? 'Traducere RU...' : 'Русский (RU)'}</span>
                  </button>
                  <button
                    onClick={() => handleLanguageChange('en')}
                    role="radio"
                    aria-checked={momLanguage === 'en'}
                    disabled={isTranslating !== null}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all whitespace-nowrap flex items-center space-x-1.5 ${
                      momLanguage === 'en'
                        ? 'bg-white text-medpark-700 shadow-xs'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    {isTranslating === 'en' ? (
                      <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin text-medpark-600" />
                    ) : (
                      <span>🇬🇧</span>
                    )}
                    <span>{isTranslating === 'en' ? 'Translating EN...' : 'English (EN)'}</span>
                  </button>
                  <button
                    onClick={() => handleLanguageChange('all')}
                    role="radio"
                    aria-checked={momLanguage === 'all'}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all whitespace-nowrap flex items-center space-x-1.5 ${
                      momLanguage === 'all'
                        ? 'bg-white text-medpark-700 shadow-xs'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <span>🌐</span>
                    <span>All 3 Languages</span>
                  </button>
                </div>
              </div>

              {isFallbackExtraction(minutes.model_version) && (
                <div
                  role="alert"
                  className="bg-amber-50 border border-amber-300 text-amber-900 p-4 rounded-2xl flex items-start space-x-2.5 shadow-xs"
                >
                  <AlertCircle className="w-5 h-5 text-amber-700 flex-shrink-0" />
                  <div className="min-w-0 space-y-0.5">
                    <p className="text-[11px] font-bold uppercase tracking-wider text-amber-800">
                      Rule-based fallback extraction
                    </p>
                    <p className="text-xs font-semibold leading-relaxed">
                      Generated by heuristic rules, not verified by neural model - please confirm all evidence against audio.
                    </p>
                    <p className="text-[11px] font-medium text-amber-800">
                      Engine: <span className="font-mono">{minutes.model_version}</span>
                    </p>
                  </div>
                </div>
              )}

              {/* Executive Summary & Revision Meta */}
              <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-xs space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <Sparkles className="w-4 h-4 text-medpark-600" />
                    <h3 className="font-bold text-sm text-slate-900">
                      {momLanguage === 'ro'
                        ? 'Rezumat Executiv Medora'
                        : momLanguage === 'ru'
                        ? 'Краткое содержание заседания (Резюме)'
                        : momLanguage === 'en'
                        ? 'Medora Executive Summary'
                        : 'Rezumat Executiv (Executive Summary)'}
                    </h3>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                      Revision {minutes.revision}
                    </span>
                    <span
                      className={`text-[10px] font-medium px-2 py-0.5 rounded border ${
                        isFallbackExtraction(minutes.model_version)
                          ? 'bg-amber-100 text-amber-900 border-amber-300 font-bold'
                          : 'bg-slate-100 text-slate-600 border-slate-200'
                      }`}
                    >
                      {minutes.model_version}
                    </span>
                  </div>

                  {!isEditingSummary ? (
                    <button
                      onClick={() => {
                        setSummaryRoEdit(minutes.summary_ro || '');
                        setSummaryRuEdit(minutes.summary_ru || '');
                        setSummaryEnEdit(minutes.summary_en || '');
                        setIsEditingSummary(true);
                      }}
                      className="inline-flex items-center space-x-1.5 text-xs text-slate-600 hover:text-medpark-600 hover:bg-slate-50 px-2.5 py-1 rounded-md border border-slate-200 transition-colors font-semibold"
                    >
                      <Edit3 className="w-3.5 h-3.5" />
                      <span>
                        {momLanguage === 'ro'
                          ? 'Editează rezumat'
                          : momLanguage === 'ru'
                          ? 'Редактировать резюме'
                          : momLanguage === 'en'
                          ? 'Edit Summary'
                          : 'Edit Summary'}
                      </span>
                    </button>
                  ) : (
                    <div className="flex items-center space-x-2">
                      <button
                        onClick={() => setIsEditingSummary(false)}
                        disabled={isSavingMinutes}
                        className="inline-flex items-center space-x-1 text-xs text-slate-500 hover:text-slate-800 px-2 py-1 rounded transition-colors"
                      >
                        <XCircle className="w-3.5 h-3.5" />
                        <span>Cancel</span>
                      </button>
                      <button
                        onClick={onSaveSummary}
                        disabled={isSavingMinutes}
                        className="inline-flex items-center space-x-1 text-xs bg-medpark-500 hover:bg-medpark-600 text-white font-bold px-3 py-1 rounded-md shadow-xs transition-colors disabled:opacity-50"
                      >
                        {isSavingMinutes ? (
                          <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" />
                        ) : (
                          <Save className="w-3.5 h-3.5" />
                        )}
                        <span>Save</span>
                      </button>
                    </div>
                  )}
                </div>

                {isEditingSummary ? (
                  <div className="space-y-4 pt-2">
                    <div>
                      <label className="text-xs font-bold text-slate-700 mb-1 flex items-center space-x-1.5">
                        <span>🇲🇩</span>
                        <span>Romanian Summary (Rezumat Executiv RO)</span>
                      </label>
                      <textarea
                        value={summaryRoEdit}
                        onChange={(e) => setSummaryRoEdit(e.target.value)}
                        rows={3}
                        placeholder="Introduceți rezumatul executiv în limba română..."
                        className="w-full text-sm text-slate-800 p-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-medpark-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-bold text-slate-700 mb-1 flex items-center space-x-1.5">
                        <span>🇷🇺</span>
                        <span>Russian Summary (Краткое содержание протокола RU)</span>
                      </label>
                      <textarea
                        value={summaryRuEdit}
                        onChange={(e) => setSummaryRuEdit(e.target.value)}
                        rows={3}
                        placeholder="Введите краткое содержание протокола на русском языке..."
                        className="w-full text-sm text-slate-800 p-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-medpark-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-bold text-slate-700 mb-1 flex items-center space-x-1.5">
                        <span>🇬🇧</span>
                        <span>English Summary (Executive Summary EN)</span>
                      </label>
                      <textarea
                        value={summaryEnEdit}
                        onChange={(e) => setSummaryEnEdit(e.target.value)}
                        rows={2}
                        placeholder="Enter executive summary in English..."
                        className="w-full text-sm text-slate-800 p-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-medpark-500 focus:outline-none"
                      />
                    </div>
                  </div>
                ) : (
                  <>
                    {momLanguage === 'all' && (
                      <div className="space-y-3 pt-1">
                        {/* RO */}
                        <div className="p-3.5 bg-slate-50/70 rounded-xl border border-slate-200/80 space-y-1.5">
                          <div className="flex items-center justify-between">
                            <span className="text-[11px] font-bold uppercase tracking-wider text-medpark-700 bg-medpark-50 px-2.5 py-0.5 rounded border border-medpark-200">
                              🇲🇩 Română (RO)
                            </span>
                          </div>
                          <p className="text-sm text-slate-800 leading-relaxed font-medium">
                            {minutes.summary_ro || (
                              <span className="text-slate-400 italic">Niciun rezumat disponibil în limba română.</span>
                            )}
                          </p>
                        </div>

                        {/* RU */}
                        <div className="p-3.5 bg-slate-50/70 rounded-xl border border-slate-200/80 space-y-1.5">
                          <div className="flex items-center justify-between">
                            <span className="text-[11px] font-bold uppercase tracking-wider text-blue-700 bg-blue-50 px-2.5 py-0.5 rounded border border-blue-200">
                              🇷🇺 Русский (RU)
                            </span>
                            {!minutes.summary_ru && (
                              <button
                                onClick={() => {
                                  setSummaryRoEdit(minutes.summary_ro || '');
                                  setSummaryRuEdit('');
                                  setSummaryEnEdit(minutes.summary_en || '');
                                  setIsEditingSummary(true);
                                }}
                                className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 hover:underline"
                              >
                                + Adaugă rezumat RU
                              </button>
                            )}
                          </div>
                          <p className="text-sm text-slate-800 leading-relaxed font-medium">
                            {minutes.summary_ru || (
                              <span className="text-slate-400 italic">
                                Резюме на русском языке еще не добавлено. Нажмите «Edit Summary», чтобы сохранить.
                              </span>
                            )}
                          </p>
                        </div>

                        {/* EN */}
                        <div className="p-3.5 bg-slate-50/70 rounded-xl border border-slate-200/80 space-y-1.5">
                          <div className="flex items-center justify-between">
                            <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded border border-emerald-200">
                              🇬🇧 English (EN)
                            </span>
                            {!minutes.summary_en && (
                              <button
                                onClick={() => {
                                  setSummaryRoEdit(minutes.summary_ro || '');
                                  setSummaryRuEdit(minutes.summary_ru || '');
                                  setSummaryEnEdit('');
                                  setIsEditingSummary(true);
                                }}
                                className="text-[11px] font-semibold text-emerald-600 hover:text-emerald-800 hover:underline"
                              >
                                + Add EN summary
                              </button>
                            )}
                          </div>
                          <p className="text-sm text-slate-800 leading-relaxed font-medium">
                            {minutes.summary_en || (
                              <span className="text-slate-400 italic">
                                No English summary available. Click &ldquo;Edit Summary&rdquo; to add.
                              </span>
                            )}
                          </p>
                        </div>
                      </div>
                    )}

                    {momLanguage === 'ro' && (
                      <div className="space-y-2 pt-1">
                        <div className="flex items-center space-x-1.5">
                          <span className="text-[11px] font-bold uppercase tracking-wider text-medpark-700 bg-medpark-50 px-2 py-0.5 rounded border border-medpark-200">
                            🇲🇩 Română (RO)
                          </span>
                        </div>
                        <p className="text-sm text-slate-800 leading-relaxed font-medium">
                          {minutes.summary_ro || (
                            <span className="text-slate-400 italic">Niciun rezumat disponibil în limba română.</span>
                          )}
                        </p>
                      </div>
                    )}

                    {momLanguage === 'ru' && (
                      <div className="space-y-2 pt-1">
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] font-bold uppercase tracking-wider text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                            🇷🇺 Русский (RU)
                          </span>
                          {!minutes.summary_ru && (
                            <button
                              onClick={() => {
                                setSummaryRoEdit(minutes.summary_ro || '');
                                setSummaryRuEdit('');
                                setSummaryEnEdit(minutes.summary_en || '');
                                setIsEditingSummary(true);
                              }}
                              className="text-xs font-semibold text-blue-600 hover:underline"
                            >
                              + Добавить резюме (RU)
                            </button>
                          )}
                        </div>
                        <p className="text-sm text-slate-800 leading-relaxed font-medium">
                          {minutes.summary_ru || (
                            <span className="text-slate-400 italic">
                              Резюме на русском языке еще не добавлено к этой сессии. Нажмите «Edit Summary», чтобы добавить.
                            </span>
                          )}
                        </p>
                      </div>
                    )}

                    {momLanguage === 'en' && (
                      <div className="space-y-2 pt-1">
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                            🇬🇧 English (EN)
                          </span>
                          {!minutes.summary_en && (
                            <button
                              onClick={() => {
                                setSummaryRoEdit(minutes.summary_ro || '');
                                setSummaryRuEdit(minutes.summary_ru || '');
                                setSummaryEnEdit('');
                                setIsEditingSummary(true);
                              }}
                              className="text-xs font-semibold text-emerald-600 hover:underline"
                            >
                              + Add English Summary
                            </button>
                          )}
                        </div>
                        <p className="text-sm text-slate-800 leading-relaxed font-medium">
                          {minutes.summary_en || (
                            <span className="text-slate-400 italic">
                              No English summary available for this session. Click &ldquo;Edit Summary&rdquo; to add one.
                            </span>
                          )}
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Agenda Topics */}
              {minutes.agenda_topics && minutes.agenda_topics.length > 0 && (
                <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-xs">
                  <div className="flex items-center space-x-2 mb-2">
                    <BookmarkCheck className="w-4 h-4 text-medpark-600" />
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
                      {momLanguage === 'ro'
                        ? 'Subiecte Agendă'
                        : momLanguage === 'ru'
                        ? 'Темы повестки заседания'
                        : momLanguage === 'en'
                        ? 'Agenda Topics'
                        : 'Subiecte Agendă (Agenda Topics)'}
                    </h4>
                  </div>
                  {momLanguage === 'all' ? (
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-medpark-50 text-medpark-700 border border-medpark-200 mr-1">
                          RO
                        </span>
                        {minutes.agenda_topics.map((topic, idx) => (
                          <span
                            key={`ro-${idx}`}
                            className="text-xs font-bold bg-slate-100 text-slate-700 px-2.5 py-0.5 rounded-md border border-slate-200"
                          >
                            {topic}
                          </span>
                        ))}
                      </div>
                      {minutes.agenda_topics_ru && minutes.agenda_topics_ru.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-slate-100">
                          <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 mr-1">
                            RU
                          </span>
                          {minutes.agenda_topics_ru.map((topic, idx) => (
                            <span
                              key={`ru-${idx}`}
                              className="text-xs font-bold bg-blue-50/50 text-blue-800 px-2.5 py-0.5 rounded-md border border-blue-200"
                            >
                              {topic}
                            </span>
                          ))}
                        </div>
                      )}
                      {minutes.agenda_topics_en && minutes.agenda_topics_en.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-slate-100">
                          <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 mr-1">
                            EN
                          </span>
                          {minutes.agenda_topics_en.map((topic, idx) => (
                            <span
                              key={`en-${idx}`}
                              className="text-xs font-bold bg-emerald-50/50 text-emerald-800 px-2.5 py-0.5 rounded-md border border-emerald-200"
                            >
                              {topic}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {(
                        (momLanguage === 'ru' && minutes.agenda_topics_ru && minutes.agenda_topics_ru.length > 0
                          ? minutes.agenda_topics_ru
                          : momLanguage === 'en' && minutes.agenda_topics_en && minutes.agenda_topics_en.length > 0
                          ? minutes.agenda_topics_en
                          : minutes.agenda_topics) || []
                      ).map((topic, idx) => (
                        <span
                          key={idx}
                          className="text-xs font-bold bg-slate-100 text-slate-700 px-2.5 py-1 rounded-md border border-slate-200"
                        >
                          {topic}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Decisions Table */}
              <DecisionsTable decisions={minutes.decisions} onSeek={onSeekAudio} language={momLanguage} />

              {/* Action Items Table */}
              <ActionItemsTable actionItems={minutes.action_items} onSeek={onSeekAudio} language={momLanguage} />

              {/* Risks and Unresolved Questions Table */}
              <RisksQuestionsTable items={minutes.risks_and_questions || []} onSeek={onSeekAudio} language={momLanguage} />
            </>
          ) : (
            <div className="bg-white rounded-2xl border border-slate-200 p-10 shadow-xs text-center">
              {isProcessing ? (
                <>
                  <Loader2 className="w-6 h-6 text-medpark-500 mx-auto motion-safe:animate-spin" />
                  <h3 className="mt-3 text-sm font-bold text-slate-900">Extracting the minutes</h3>
                  <p className="mt-1 text-xs text-slate-600 max-w-md mx-auto leading-relaxed">
                    Decisions, action items and evidence quotes appear here once the pipeline reaches the extraction stage.
                  </p>
                </>
              ) : selectedMeeting.processing_status === 'failed' ? (
                <>
                  <AlertCircle className="w-6 h-6 text-rose-600 mx-auto" />
                  <h3 className="mt-3 text-sm font-bold text-slate-900">Pipeline Failed</h3>
                  <p className="mt-1 text-xs text-slate-600 max-w-md mx-auto leading-relaxed">
                    {selectedMeeting.error_message || 'The pipeline stopped before minutes could be generated.'}
                  </p>
                </>
              ) : (
                <>
                  <FileText className="w-6 h-6 text-slate-400 mx-auto" />
                  <h3 className="mt-3 text-sm font-bold text-slate-900">No minutes generated yet</h3>
                  <p className="mt-1 text-xs text-slate-600 max-w-md mx-auto leading-relaxed">
                    Check the transcript to confirm speech was detected.
                  </p>
                  <button
                    onClick={() => setActiveTab('transcript')}
                    className="mt-4 inline-flex items-center space-x-1.5 px-3 py-2 bg-white border border-slate-200 text-slate-700 text-xs font-bold rounded-xl hover:bg-slate-50 transition-colors"
                  >
                    <Layers className="w-3.5 h-3.5 text-slate-500" />
                    <span>Open transcript</span>
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Multilingual Transcript */}
      {activeTab === 'transcript' && (
        <div role="tabpanel" id="panel-transcript" className="space-y-6">
          {selectedMeeting && (
            <SpeakerAssignmentCard
              meetingId={selectedMeeting.id}
              revision={minutes?.revision ?? null}
              attendees={selectedMeeting.attendees}
              onAttributionChanged={onAttributionChanged}
            />
          )}

          {transcript ? (
            <TranscriptViewer
              segments={transcript.segments}
              onSeek={onSeekAudio}
              onUpdateSegment={onUpdateSegment}
              currentTime={playbackTime}
            />
          ) : (
            <div className="bg-white rounded-2xl border border-slate-200 p-10 shadow-xs text-center">
              {isProcessing ? (
                <>
                  <Loader2 className="w-6 h-6 text-medpark-500 mx-auto motion-safe:animate-spin" />
                  <h3 className="mt-3 text-sm font-bold text-slate-900">Generating multilingual transcript</h3>
                  <p className="mt-1 text-xs text-slate-600 max-w-md mx-auto leading-relaxed">
                    Speaker-attributed utterances appear here after transcription and diarization complete.
                  </p>
                </>
              ) : (
                <>
                  <Layers className="w-6 h-6 text-slate-400 mx-auto" />
                  <h3 className="mt-3 text-sm font-bold text-slate-900">No transcript available</h3>
                  <p className="mt-1 text-xs text-slate-600 max-w-md mx-auto leading-relaxed">
                    {selectedMeeting.original_audio_path
                      ? 'The recording was processed but produced no speech segments. Play the audio above to verify recording.'
                      : 'This meeting has no recording yet.'}
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
