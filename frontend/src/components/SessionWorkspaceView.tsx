import React from 'react';
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
} from 'lucide-react';

interface SessionWorkspaceViewProps {
  meetings: Meeting[];
  selectedMeeting: Meeting | null;
  onSelectMeeting: (id: string) => void;
  onBackToDashboard: () => void;
  minutes: MinutesOfMeeting | null;
  transcript: Transcript | null;
  isProcessing: boolean;
  pipelineProgress: number;
  pipelineStage: string;
  stageDetail: string;
  activeTab: 'minutes' | 'transcript';
  setActiveTab: (tab: 'minutes' | 'transcript') => void;
  playbackTime: number;
  setPlaybackTime: (time: number) => void;
  playbackBucketRef: React.MutableRefObject<number>;
  waveformRef: React.RefObject<WaveformPlayerRef>;
  onCopyFullMoM: () => void;
  onDeleteMeeting: (meeting: Meeting) => void;
  onOpenApproval: () => void;
  onOpenIntake: () => void;
  isEditingSummary: boolean;
  setIsEditingSummary: (v: boolean) => void;
  summaryRoEdit: string;
  setSummaryRoEdit: (v: string) => void;
  summaryEnEdit: string;
  setSummaryEnEdit: (v: string) => void;
  isSavingMinutes: boolean;
  onSaveSummary: () => void;
  onUpdateSegment: (segmentId: string, text: string) => Promise<void>;
  onSeekAudio: (time: number) => void;
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
  minutes,
  transcript,
  isProcessing,
  pipelineProgress,
  pipelineStage,
  stageDetail,
  activeTab,
  setActiveTab,
  playbackTime,
  setPlaybackTime,
  playbackBucketRef,
  waveformRef,
  onCopyFullMoM,
  onDeleteMeeting,
  onOpenApproval,
  onOpenIntake,
  isEditingSummary,
  setIsEditingSummary,
  summaryRoEdit,
  setSummaryRoEdit,
  summaryEnEdit,
  setSummaryEnEdit,
  isSavingMinutes,
  onSaveSummary,
  onUpdateSegment,
  onSeekAudio,
}) => {
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
          : null;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Top Workspace Bar: Navigation & Quick Session Switcher */}
      <div className="bg-white p-4 rounded-2xl border border-slate-200/90 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <button
            onClick={onBackToDashboard}
            className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-xl text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 transition-colors"
            title="Return to Dashboard view"
          >
            <ChevronLeft className="w-4 h-4" />
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
      <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-xs flex flex-col lg:flex-row lg:items-start justify-between gap-4">
        <div className="space-y-1.5 min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="text-xl font-black text-slate-900 tracking-tight">
              {selectedMeeting.title}
            </h2>
            <span className="text-xs font-bold uppercase px-2.5 py-0.5 rounded-md bg-medpark-50 text-medpark-700 border border-medpark-500/20">
              {selectedMeeting.meeting_type}
            </span>

            <span
              className={`inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-md text-xs font-bold border ${
                selectedMeeting.workflow_mode === 'auto_pilot'
                  ? 'bg-blue-50 text-blue-800 border-blue-200'
                  : 'bg-emerald-50 text-emerald-800 border-emerald-200'
              }`}
            >
              {selectedMeeting.workflow_mode === 'auto_pilot' ? (
                <>
                  <Rocket className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Auto-Pilot (Zero-Click)</span>
                </>
              ) : (
                <>
                  <Shield className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Supervised (Clinical Gate)</span>
                </>
              )}
            </span>

            {selectedMeeting.review_status === 'delivered' && (
              <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-md text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" aria-hidden="true" />
                <span>Delivered via Email</span>
              </span>
            )}

            {selectedMeeting.review_status === 'approved' && (
              <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-md text-xs font-bold bg-amber-100 text-amber-900 border border-amber-300">
                <AlertCircle className="w-3.5 h-3.5 text-amber-700" aria-hidden="true" />
                <span>Signed - Not Delivered</span>
              </span>
            )}

            {selectedMeeting.processing_status === 'failed' && (
              <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-md text-xs font-bold bg-rose-50 text-rose-700 border border-rose-200">
                <AlertCircle className="w-3.5 h-3.5 text-rose-600" aria-hidden="true" />
                <span>Pipeline Failed</span>
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 font-medium pt-1">
            <span className="flex items-center space-x-1">
              <Calendar className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
              <span>{new Date(selectedMeeting.scheduled_at).toLocaleString()}</span>
            </span>
            <span className="flex items-center space-x-1">
              <Clock className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
              <span>
                Audio:{' '}
                <span className="font-mono tabular-nums">
                  {selectedMeeting.audio_duration_seconds.toFixed(1)}s
                </span>
              </span>
            </span>
            <span className="flex items-center space-x-1">
              <Users className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
              <span>
                <span className="tabular-nums">{selectedMeeting.attendees.length}</span> participants
              </span>
            </span>
            {selectedMeeting.processing_time_seconds > 0 && (
              <span className="flex items-center space-x-1 font-mono tabular-nums text-emerald-700 font-bold">
                <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Pipeline: {selectedMeeting.processing_time_seconds}s</span>
              </span>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col gap-2 lg:items-end flex-shrink-0">
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            {minutes && (
              <button
                onClick={onCopyFullMoM}
                className="inline-flex items-center space-x-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-xl transition-colors"
                title="Copy executive summary, decisions, and action items as Markdown"
              >
                <Copy className="w-3.5 h-3.5 text-slate-500" />
                <span>Copy Full MoM</span>
              </button>
            )}

            {minutes && (
              <>
                <a
                  href={apiClient.getPdfDownloadUrl(selectedMeeting.id)}
                  download
                  className="inline-flex items-center space-x-1.5 px-3 py-2 bg-rose-50 hover:bg-rose-100 text-rose-800 border border-rose-200 text-xs font-bold rounded-xl transition-colors"
                  title="Download official PDF report"
                >
                  <FileDown className="w-3.5 h-3.5 text-rose-600" />
                  <span>PDF</span>
                </a>

                <a
                  href={apiClient.getDocxDownloadUrl(selectedMeeting.id)}
                  download
                  className="inline-flex items-center space-x-1.5 px-3 py-2 bg-blue-50 hover:bg-blue-100 text-blue-800 border border-blue-200 text-xs font-bold rounded-xl transition-colors"
                  title="Download official Word DOCX report"
                >
                  <FileDown className="w-3.5 h-3.5 text-blue-600" />
                  <span>DOCX</span>
                </a>
              </>
            )}

            <button
              onClick={() => onDeleteMeeting(selectedMeeting)}
              className="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-xl transition-colors border border-slate-200"
              title="Delete meeting record"
              aria-label="Delete meeting record"
            >
              <Trash2 className="w-4 h-4" />
            </button>

            {selectedMeeting.workflow_mode === 'supervised' &&
              selectedMeeting.review_status !== 'delivered' && (
                <>
                  <span className="hidden sm:block w-px h-7 bg-slate-200" aria-hidden="true" />
                  <button
                    onClick={onOpenApproval}
                    disabled={signOffBlockedReason !== null}
                    title={signOffBlockedReason || 'Sign off and dispatch the official minutes'}
                    className="inline-flex items-center space-x-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold rounded-xl shadow-xs transition-colors disabled:bg-slate-200 disabled:text-slate-500 disabled:cursor-not-allowed"
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
              <p className="text-[11px] font-medium text-slate-500 lg:text-right max-w-xs">
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
          <span>Multilingual Transcript &amp; Speakers</span>
          {transcript && (
            <span className="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-bold tabular-nums">
              {transcript.segments.length}
            </span>
          )}
        </button>
      </div>

      {/* Tab 1: Minutes Content */}
      {activeTab === 'minutes' && (
        <div role="tabpanel" id="panel-minutes" className="space-y-6">
          {minutes ? (
            <>
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
                    <h3 className="font-bold text-sm text-slate-900">Medora Executive Summary</h3>
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
                        setSummaryEnEdit(minutes.summary_en || '');
                        setIsEditingSummary(true);
                      }}
                      className="inline-flex items-center space-x-1.5 text-xs text-slate-600 hover:text-medpark-600 hover:bg-slate-50 px-2.5 py-1 rounded-md border border-slate-200 transition-colors font-semibold"
                    >
                      <Edit3 className="w-3.5 h-3.5" />
                      <span>Edit Summary</span>
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
                  <div className="space-y-3 pt-2">
                    <div>
                      <label className="block text-xs font-semibold text-slate-700 mb-1">
                        Romanian Summary
                      </label>
                      <textarea
                        value={summaryRoEdit}
                        onChange={(e) => setSummaryRoEdit(e.target.value)}
                        rows={3}
                        className="w-full text-sm text-slate-800 p-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-medpark-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-slate-700 mb-1">
                        English Summary
                      </label>
                      <textarea
                        value={summaryEnEdit}
                        onChange={(e) => setSummaryEnEdit(e.target.value)}
                        rows={2}
                        className="w-full text-sm text-slate-800 p-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-medpark-500 focus:outline-none"
                      />
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="text-sm text-slate-800 leading-relaxed font-medium">{minutes.summary_ro}</p>
                    {minutes.summary_en && (
                      <p className="text-xs text-slate-600 italic pt-2 border-t border-slate-100">
                        <span className="font-bold text-slate-700 not-italic mr-1">[English Translation]</span>
                        {minutes.summary_en}
                      </p>
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
                      Agenda Topics
                    </h4>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {minutes.agenda_topics.map((topic, idx) => (
                      <span
                        key={idx}
                        className="text-xs font-bold bg-slate-100 text-slate-700 px-2.5 py-1 rounded-md border border-slate-200"
                      >
                        {topic}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Decisions Table */}
              <DecisionsTable decisions={minutes.decisions} onSeek={onSeekAudio} />

              {/* Action Items Table */}
              <ActionItemsTable actionItems={minutes.action_items} onSeek={onSeekAudio} />

              {/* Risks and Unresolved Questions Table */}
              <RisksQuestionsTable items={minutes.risks_and_questions || []} onSeek={onSeekAudio} />
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
        <div role="tabpanel" id="panel-transcript">
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
