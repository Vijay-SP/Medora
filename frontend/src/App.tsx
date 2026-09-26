import React, { useState, useEffect, useRef } from 'react';
import { Meeting, Transcript, MinutesOfMeeting, MeetingCreate, ReadinessResponse } from './types';
import { apiClient } from './api/client';
import { useToast } from './components/Toast';
import { Navbar } from './components/Navbar';
import { Sidebar, AppPage } from './components/Sidebar';
import { DashboardView } from './components/DashboardView';
import { SessionWorkspaceView } from './components/SessionWorkspaceView';
import { LiveMeetingStudio } from './components/LiveMeetingStudio';
import { DeliveriesView } from './components/DeliveriesView';
import { SettingsView } from './components/SettingsView';
import { ReviewApprovalModal } from './components/ReviewApprovalModal';
import { MeetingIntakeModal } from './components/MeetingIntakeModal';
import { DeliveryOutboxDrawer } from './components/DeliveryOutboxDrawer';
import { KeyboardShortcutsModal } from './components/KeyboardShortcutsModal';
import { WaveformPlayerRef } from './components/WaveformPlayer';
import { PeoplePage } from './components/voice/PeoplePage';
import { SpeakerConfirmationPanel } from './components/voice/SpeakerConfirmationPanel';
import { Trash2, AlertCircle } from 'lucide-react';

// Workspace tabs. 'speakers' exists only while /ready reports voice identification as enabled.
type WorkspaceTab = 'minutes' | 'transcript' | 'speakers';

const copyTextToClipboard = async (text: string): Promise<boolean> => {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.error('Clipboard API write failed, trying fallback:', err);
    }
  }

  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(textarea);
    return copied;
  } catch (err) {
    console.error('Legacy fallback failed:', err);
    return false;
  }
};

// Short reviewer-facing tag for how an action owner was resolved (see ActionItem.owner_source).
const OWNER_SOURCE_LABELS: Record<string, string> = {
  roster: 'roster',
  mention: 'named in audio, not on roster',
  speaker: 'anonymous speaker label',
  unassigned: 'unassigned',
};

const PIPELINE_STAGES: { key: string; label: string }[] = [
  { key: 'preprocessing', label: 'Audio preprocessing' },
  { key: 'transcribing', label: 'Transcription' },
  { key: 'diarizing', label: 'Speaker diarization' },
  { key: 'extracting', label: 'Minutes extraction' },
  { key: 'generating_docs', label: 'Document generation' },
];

export const App: React.FC = () => {
  const { showToast } = useToast();

  // Navigation State
  const [currentPage, setCurrentPage] = useState<AppPage>('dashboard');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  // Meetings and active session state
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState<string | null>(null);
  const [selectedMeeting, setSelectedMeeting] = useState<Meeting | null>(null);

  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [minutes, setMinutes] = useState<MinutesOfMeeting | null>(null);

  const [activeTab, setActiveTab] = useState<WorkspaceTab>('minutes');
  const [playbackTime, setPlaybackTime] = useState<number>(0);

  // Voice identification: People & Voices replaces the page area; the Speakers tab lives in the
  // workspace. Both exist only when the backend reports the feature enabled AND the embedder present.
  const [view, setView] = useState<'workspace' | 'people'>('workspace');
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const voiceIdEnabled = Boolean(readiness?.voice_id?.enabled);
  const [speakersReloadKey, setSpeakersReloadKey] = useState(0);

  // Search & Filter
  const [meetingSearchQuery, setMeetingSearchQuery] = useState('');
  const [workflowModeFilter, setWorkflowModeFilter] = useState<string>('all');
  const [reviewStatusFilter, setReviewStatusFilter] = useState<string>('all');

  // Modals & Drawers
  const [isIntakeOpen, setIsIntakeOpen] = useState(false);
  const [intakeInitialMode, setIntakeInitialMode] = useState<'upload' | 'live'>('upload');
  const [isApprovalOpen, setIsApprovalOpen] = useState(false);
  const [isOutboxOpen, setIsOutboxOpen] = useState(false);
  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);
  const [meetingToDelete, setMeetingToDelete] = useState<Meeting | null>(null);

  // Minutes Editing
  const [isEditingSummary, setIsEditingSummary] = useState(false);
  const [summaryRoEdit, setSummaryRoEdit] = useState('');
  const [summaryEnEdit, setSummaryEnEdit] = useState('');
  const [isSavingMinutes, setIsSavingMinutes] = useState(false);

  // Pipeline Status & Progress
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [pipelineProgress, setPipelineProgress] = useState(0);
  const [stageDetail, setStageDetail] = useState<string>('');
  const [pipelineStage, setPipelineStage] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const waveformRef = useRef<WaveformPlayerRef>(null);
  const selectedMeetingIdRef = useRef<string | null>(selectedMeetingId);
  const deleteCancelRef = useRef<HTMLButtonElement>(null);
  const pipelineStartedIdRef = useRef<string | null>(null);
  const statusPollInFlightRef = useRef(false);
  const playbackBucketRef = useRef<number>(-1);

  useEffect(() => {
    selectedMeetingIdRef.current = selectedMeetingId;
  }, [selectedMeetingId]);

  useEffect(() => {
    loadMeetings();
  }, []);

  useEffect(() => {
    if (selectedMeetingId) {
      loadMeetingData(selectedMeetingId);
    }
  }, [selectedMeetingId]);

  // Polling pipeline status
  useEffect(() => {
    let interval: number | null = null;
    if (isProcessing && selectedMeetingId) {
      interval = window.setInterval(async () => {
        if (statusPollInFlightRef.current) return;
        statusPollInFlightRef.current = true;
        try {
          const status = await apiClient.getPipelineStatus(selectedMeetingId);
          setPipelineProgress(status.progress);
          setStageDetail(status.current_stage || '');
          if (PIPELINE_STAGES.some((s) => s.key === status.status)) {
            setPipelineStage(status.status);
          }

          if (status.status === 'completed' || status.status === 'failed') {
            pipelineStartedIdRef.current = null;
            setIsProcessing(false);
            if (interval) clearInterval(interval);
            loadMeetingData(selectedMeetingId);
            loadMeetings();
            setSpeakersReloadKey((k) => k + 1);
          } else if (status.status !== 'idle') {
            pipelineStartedIdRef.current = null;
          }
        } catch (err) {
          console.error('Error polling pipeline status:', err);
        } finally {
          statusPollInFlightRef.current = false;
        }
      }, 1500);
    }
    return () => {
      if (interval) clearInterval(interval);
      statusPollInFlightRef.current = false;
    };
  }, [isProcessing, selectedMeetingId]);

  // Global Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (isIntakeOpen || isApprovalOpen || isOutboxOpen || isShortcutsOpen || meetingToDelete) {
        if (e.key === 'Escape') {
          e.preventDefault();
          if (isShortcutsOpen) setIsShortcutsOpen(false);
          else if (isOutboxOpen) setIsOutboxOpen(false);
          else if (isApprovalOpen) setIsApprovalOpen(false);
          else if (isIntakeOpen) setIsIntakeOpen(false);
          else setMeetingToDelete(null);
        }
        return;
      }

      // People & Voices owns its own dialogs (consent drawer, delete confirmations) and Escape handling.
      if (view === 'people') return;

      const activeElement = document.activeElement as HTMLElement | null;
      const activeTag = activeElement?.tagName;
      if (
        activeTag === 'INPUT' ||
        activeTag === 'TEXTAREA' ||
        activeTag === 'SELECT' ||
        activeElement?.isContentEditable
      ) {
        return;
      }

      if (e.key === ' ' || e.code === 'Space') {
        if (activeTag === 'BUTTON' || activeTag === 'A') return;
        e.preventDefault();
        waveformRef.current?.togglePlay();
      } else if (e.key === '?') {
        e.preventDefault();
        setIsShortcutsOpen((prev) => !prev);
      } else if (e.key === 'm' || e.key === 'M') {
        e.preventDefault();
        setIntakeInitialMode('upload');
        setIsIntakeOpen(true);
      } else if (e.key === 'o' || e.key === 'O') {
        e.preventDefault();
        setCurrentPage('deliveries');
      } else if (e.key === '1') {
        setActiveTab('minutes');
      } else if (e.key === '2') {
        setActiveTab('transcript');
      } else if (e.key === '3' && voiceIdEnabled) {
        setActiveTab('speakers');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isIntakeOpen, isApprovalOpen, isOutboxOpen, isShortcutsOpen, meetingToDelete, view, voiceIdEnabled]);

  // The Speakers tab cannot outlive the feature flag: fall back to the minutes when it turns off.
  useEffect(() => {
    if (!voiceIdEnabled && activeTab === 'speakers') setActiveTab('minutes');
  }, [voiceIdEnabled, activeTab]);

  useEffect(() => {
    if (meetingToDelete) deleteCancelRef.current?.focus();
  }, [meetingToDelete]);

  const loadMeetings = async () => {
    try {
      const data = await apiClient.listMeetings();
      setMeetings(data);
      if (data.length > 0 && !selectedMeetingId) {
        setSelectedMeetingId(data[0].id);
      }
    } catch (err: any) {
      console.error('Failed to load meetings:', err);
      setErrorMessage('Failed to load meetings from server.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectMeeting = (id: string) => {
    if (id !== selectedMeetingId) {
      setSelectedMeetingId(id);
      setSelectedMeeting(null);
      setTranscript(null);
      setMinutes(null);
      setIsProcessing(false);
      setIsEditingSummary(false);
      setPlaybackTime(0);
      setPipelineStage('');
      playbackBucketRef.current = -1;
    }
  };

  const loadMeetingData = async (id: string) => {
    try {
      const m = await apiClient.getMeeting(id);
      if (selectedMeetingIdRef.current !== id) return;
      setSelectedMeeting(m);

      if (
        ['preprocessing', 'transcribing', 'diarizing', 'extracting', 'generating_docs'].includes(
          m.processing_status
        )
      ) {
        pipelineStartedIdRef.current = null;
        setIsProcessing(true);
        setPipelineProgress(m.processing_progress);
        setStageDetail(m.current_stage_detail || '');
        setPipelineStage(m.processing_status);
      } else {
        if (pipelineStartedIdRef.current === id) {
          pipelineStartedIdRef.current = null;
        }
        setIsProcessing(false);
      }

      // Transcript
      try {
        const t = await apiClient.getTranscript(id);
        if (selectedMeetingIdRef.current === id) setTranscript(t);
      } catch {
        if (selectedMeetingIdRef.current === id) setTranscript(null);
      }

      // Minutes
      try {
        const min = await apiClient.getMinutes(id);
        if (selectedMeetingIdRef.current === id) {
          setMinutes(min);
          setSummaryRoEdit(min.summary_ro || '');
          setSummaryEnEdit(min.summary_en || '');
        }
      } catch {
        if (selectedMeetingIdRef.current === id) setMinutes(null);
      }
    } catch (err) {
      console.error('Failed to load meeting details:', err);
    }
  };

  const handleCreateMeeting = async (payload: MeetingCreate, file?: File) => {
    setErrorMessage(null);
    let created: Meeting;
    try {
      created = await apiClient.createMeeting(payload);
    } catch (err: any) {
      console.error('Error creating meeting:', err);
      setErrorMessage(`Failed to create meeting: ${err?.message || 'Server error'}`);
      showToast('Creation failed', err?.message || 'Server error', 'error');
      throw err;
    }

    let pipelineError: any = null;
    if (file) {
      try {
        await apiClient.uploadAudio(created.id, file);
        await apiClient.startPipeline(created.id);
        pipelineStartedIdRef.current = created.id;
        setIsProcessing(true);
        setPipelineProgress(5);
        setPipelineStage('preprocessing');
        setStageDetail('Initializing audio pipeline...');
      } catch (err: any) {
        console.error('Error starting pipeline:', err);
        pipelineError = err;
      }
    }

    await loadMeetings();
    setSelectedMeetingId(created.id);
    setCurrentPage('workspace');

    if (pipelineError) {
      setErrorMessage(
        `Meeting "${created.title}" was created, but the pipeline could not start: ${pipelineError?.message || 'Server error'}`
      );
      showToast('Pipeline not started', pipelineError?.message || 'Server error', 'error');
      return;
    }

    showToast(
      'Session Created',
      file
        ? `Meeting "${created.title}" started processing with Medora AI.`
        : `Meeting "${created.title}" created. Audio can be added later.`
    );
  };

  const handleDeleteMeeting = async (id: string) => {
    try {
      await apiClient.deleteMeeting(id);
      showToast('Meeting Deleted', 'Meeting record removed from repository.');
      setMeetingToDelete(null);
      const remaining = meetings.filter((m) => m.id !== id);
      setMeetings(remaining);
      if (selectedMeetingId === id) {
        setSelectedMeeting(null);
        setTranscript(null);
        setMinutes(null);
        setIsProcessing(false);
        setIsEditingSummary(false);
        setPlaybackTime(0);
        setPipelineStage('');
        playbackBucketRef.current = -1;
        setSelectedMeetingId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err: any) {
      console.error('Failed to delete meeting:', err);
      showToast('Deletion failed', err?.message || 'Could not delete meeting', 'error');
    }
  };

  const handleSaveSummary = async () => {
    if (!selectedMeetingId || !minutes) return;
    setIsSavingMinutes(true);
    setErrorMessage(null);
    try {
      const updated = await apiClient.updateMinutes(selectedMeetingId, {
        ...minutes,
        summary_ro: summaryRoEdit,
        summary_en: summaryEnEdit,
      });
      setMinutes(updated);
      setIsEditingSummary(false);
      showToast('Summary Saved', `Updated executive summary saved for Revision ${updated.revision}.`);
      await loadMeetingData(selectedMeetingId);
      await loadMeetings();
    } catch (err: any) {
      console.error('Failed to update minutes:', err);
      setErrorMessage(`Failed to update summary: ${err?.message || 'Server error'}`);
      showToast('Save failed', err?.message || 'Could not save summary', 'error');
    } finally {
      setIsSavingMinutes(false);
    }
  };

  const handleUpdateSegment = async (segmentId: string, correctedText: string) => {
    if (!selectedMeetingId) return;
    await apiClient.updateSegment(selectedMeetingId, segmentId, { corrected_text: correctedText });

    try {
      const updated = await apiClient.getTranscript(selectedMeetingId);
      setTranscript(updated);
    } catch (err) {
      console.error('Failed to refresh transcript after correction:', err);
      setTranscript((prev) =>
        prev
          ? {
              ...prev,
              segments: prev.segments.map((s) =>
                s.id === segmentId
                  ? { ...s, corrected_text: correctedText, display_text: correctedText }
                  : s
              ),
            }
          : prev
      );
    }
  };

  const handleApprove = async (reviewerName: string, reviewerRole: string, comments: string) => {
    if (!selectedMeetingId) return;
    setErrorMessage(null);
    try {
      const result = await apiClient.approveMeeting(selectedMeetingId, {
        reviewer_name: reviewerName,
        reviewer_role: reviewerRole,
        comments,
        expected_revision: minutes?.revision,
      });

      await loadMeetingData(selectedMeetingId);
      await loadMeetings();

      const delivery = result?.delivery_record || null;
      if (delivery?.status === 'dispatched') {
        showToast(
          'Minutes Dispatched',
          `Signed minutes emailed to ${delivery.recipients?.length || 0} recipient(s).`
        );
      } else if (delivery?.status === 'simulated') {
        showToast(
          'Minutes Signed (Simulated Outbox)',
          `Delivery simulated to ${delivery.recipients?.length || 0} recipients.`
        );
      } else if (delivery?.status === 'failed') {
        showToast('Signed, but Email Failed', delivery.error_message || 'SMTP failed', 'error');
      } else {
        showToast('Minutes Approved', 'Sign-off recorded successfully.');
      }
    } catch (err: any) {
      console.error('Approval failed:', err);
      setErrorMessage(`Clinical sign-off failed: ${err?.message || 'Server error'}`);
      showToast('Sign-off failed', err?.message || 'Server error', 'error');
      throw err;
    }
  };

  const handleSeekAudio = (time: number) => {
    waveformRef.current?.seekToSeconds(time);
  };

  // Bounded playback for speaker review clips; a bare start behaves like a plain seek.
  const handlePlayRange = (start: number, end?: number) => {
    if (typeof end === 'number' && end > start) {
      waveformRef.current?.playRange(start, end);
    } else {
      waveformRef.current?.seekToSeconds(start);
    }
  };

  // The transcript viewer renders seg.speaker; feed it the backend's display_speaker (a confirmed
  // name only on printable turns, the anonymous label otherwise) without widening its props.
  const transcriptForDisplay: Transcript | null = transcript
    ? {
        ...transcript,
        segments: transcript.segments.map((s) => ({ ...s, speaker: s.display_speaker ?? s.speaker })),
      }
    : null;

  const handleCopyFullMoM = async () => {
    if (!minutes || !selectedMeeting) return;
    const lines: string[] = [
      `# ${selectedMeeting.title}`,
      `**Data / Date:** ${new Date(selectedMeeting.scheduled_at).toLocaleString()}`,
      `**Tip / Type:** ${selectedMeeting.meeting_type.toUpperCase()} | **Rev.** ${minutes.revision}`,
      `**Model / Engine:** ${minutes.model_version}`,
    ];
    // Provenance travels with the text: a degraded draft must never be pasted as if validated.
    if (minutes.is_degraded) {
      lines.push('', '> DRAFT NEVALIDAT - LLM LOCAL INDISPONIBIL (heuristic fallback, not dispatchable)');
    }
    if (minutes.needs_name_review) {
      lines.push('', '> Verificare nume necesara - a non-roster owner or proper noun needs confirmation');
    }
    lines.push('', '## Executive Summary (RO)', minutes.summary_ro);

    if (minutes.summary_en) {
      lines.push('', '## Executive Summary (EN)', minutes.summary_en);
    }

    if (minutes.decisions && minutes.decisions.length > 0) {
      lines.push('', '## Decisions & Agreements');
      minutes.decisions.forEach((d, idx) => {
        lines.push(`${idx + 1}. **[${d.topic}]** ${d.decision}`);
      });
    }

    if (minutes.action_items && minutes.action_items.length > 0) {
      lines.push('', '## Action Items');
      minutes.action_items.forEach((a, idx) => {
        const owner = a.owner || 'Unassigned';
        const ownerHint =
          a.owner_source && a.owner_source !== 'roster' && a.owner_source !== 'unassigned'
            ? ` (${OWNER_SOURCE_LABELS[a.owner_source] || a.owner_source})`
            : '';
        const deadline = a.deadline_date || a.deadline_phrase || 'TBD';
        lines.push(`${idx + 1}. **${a.task}** - *Responsible:* ${owner}${ownerHint} | *Deadline:* ${deadline}`);
      });
    }

    const fullText = lines.join('\n');
    const copied = await copyTextToClipboard(fullText);
    if (copied) {
      showToast('Copied MoM', 'Executive summary, decisions, and actions copied as Markdown.');
    } else {
      showToast('Copy failed', 'Clipboard access unavailable. Use PDF/DOCX download instead.', 'error');
    }
  };

  const clearMeetingFilters = () => {
    setMeetingSearchQuery('');
    setWorkflowModeFilter('all');
    setReviewStatusFilter('all');
  };

  // Review flags on the loaded revision, surfaced above the workspace so they cannot be missed.
  const failedChunkCount = minutes?.failed_chunks?.length ?? 0;
  const showReviewFlags = Boolean(
    minutes && (minutes.is_degraded || minutes.needs_name_review || failedChunkCount > 0)
  );

  const pendingCount = meetings.filter(
    (m) =>
      m.review_status === 'pending_review' ||
      m.review_status === 'draft' ||
      m.review_status === 'approved'
  ).length;

  const getPageTitle = (page: AppPage): string => {
    if (view === 'people') return 'People & Voices';
    switch (page) {
      case 'dashboard':
        return 'Executive Dashboard';
      case 'workspace':
        return selectedMeeting ? `Workspace: ${selectedMeeting.title}` : 'Session Workspace';
      case 'live':
        return 'Live Meeting Room (Conference Mic)';
      case 'deliveries':
        return 'Email Governance & Deliveries';
      case 'settings':
        return 'System & Air-Gap Security';
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex font-sans text-slate-800 antialiased">
      {/* Accessible skip link */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:top-2 focus:left-2 focus:px-3 focus:py-2 focus:bg-white focus:text-medpark-700 focus:text-xs focus:font-bold focus:rounded-lg focus:border focus:border-medpark-500 shadow-md"
      >
        Skip to main content
      </a>

      {/* Persistent Left Sidebar */}
      <Sidebar
        currentPage={currentPage}
        onNavigate={(page) => {
          setView('workspace');
          setCurrentPage(page);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }}
        onStartLiveMeeting={() => {
          setView('workspace');
          setCurrentPage('live');
        }}
        onUploadRecording={() => {
          setIntakeInitialMode('upload');
          setIsIntakeOpen(true);
        }}
        selectedMeeting={selectedMeeting}
        totalMeetingsCount={meetings.length}
        pendingReviewsCount={pendingCount}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
      />

      {/* Main Workspace Frame */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen">
        {/* Top Navbar */}
        <Navbar
          onNewMeeting={() => {
            setIntakeInitialMode('upload');
            setIsIntakeOpen(true);
          }}
          onOpenDeliveries={() => {
            setView('workspace');
            setCurrentPage('deliveries');
          }}
          onOpenShortcuts={() => setIsShortcutsOpen(true)}
          onToggleSidebar={() => setIsSidebarCollapsed((prev) => !prev)}
          currentPageTitle={getPageTitle(currentPage)}
          meetingsCount={meetings.length}
          onOpenPeople={() => setView((v) => (v === 'people' ? 'workspace' : 'people'))}
          isPeopleActive={view === 'people'}
          onReadinessChange={setReadiness}
        />

        {/* Action-required Error Banner */}
        {errorMessage && (
          <div
            role="alert"
            className="m-4 sm:m-6 lg:m-8 mb-0 p-4 bg-rose-50 border border-rose-200 text-rose-800 rounded-2xl flex items-center justify-between gap-3 shadow-xs"
          >
            <div className="flex items-center space-x-2.5 min-w-0">
              <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />
              <p className="text-xs font-semibold leading-relaxed break-words">{errorMessage}</p>
            </div>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-xs font-bold px-3 py-1 bg-white border border-rose-200 rounded-lg text-rose-700 hover:bg-rose-100 transition-colors flex-shrink-0"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Extraction provenance / review flags banner (workspace only) */}
        {view === 'workspace' && currentPage === 'workspace' && minutes && showReviewFlags && (
          <div
            role="alert"
            className={`m-4 sm:m-6 lg:m-8 mb-0 p-4 rounded-2xl border flex items-start gap-3 shadow-xs ${
              minutes.is_degraded
                ? 'bg-rose-50 border-rose-200 text-rose-800'
                : 'bg-amber-50 border-amber-300 text-amber-900'
            }`}
          >
            <AlertCircle
              className={`w-5 h-5 flex-shrink-0 ${minutes.is_degraded ? 'text-rose-600' : 'text-amber-700'}`}
            />
            <div className="min-w-0 space-y-1 text-xs">
              <p className="text-[11px] font-bold uppercase tracking-wider">
                {minutes.is_degraded
                  ? 'Unvalidated draft - local LLM was unavailable'
                  : 'Review flags on this revision'}
              </p>
              <ul className="list-disc list-inside font-medium leading-relaxed space-y-0.5">
                {minutes.is_degraded && (
                  <li>
                    Produced by the rule-based fallback; sign-off and email dispatch are blocked until
                    the pipeline is re-run with the local LLM.
                  </li>
                )}
                {minutes.needs_name_review && (
                  <li>Name review needed: an action owner or proper noun is not on the attendee roster.</li>
                )}
                {failedChunkCount > 0 && (
                  <li>
                    {failedChunkCount} transcript fragment{failedChunkCount === 1 ? '' : 's'} failed
                    extraction - see the audit note under Risks &amp; Questions.
                  </li>
                )}
              </ul>
              <p className="text-[11px] font-mono break-all opacity-80">Model: {minutes.model_version}</p>
            </div>
          </div>
        )}

        {/* Dynamic Page Views */}
        <main id="main-content" className="flex-1 p-4 sm:p-6 lg:p-8 overflow-y-auto">
          {/* People & Voices: full-width, in place of whichever page was open */}
          {view === 'people' && <PeoplePage onBack={() => setView('workspace')} />}

          {/* Page 1: Dashboard View */}
          {view === 'workspace' && currentPage === 'dashboard' && (
            <DashboardView
              meetings={meetings}
              selectedMeetingId={selectedMeetingId}
              onSelectMeeting={handleSelectMeeting}
              onOpenWorkspace={(id) => {
                handleSelectMeeting(id);
                setCurrentPage('workspace');
              }}
              onStartLiveMeeting={() => setCurrentPage('live')}
              onUploadRecording={() => {
                setIntakeInitialMode('upload');
                setIsIntakeOpen(true);
              }}
              onDeleteMeeting={(m) => setMeetingToDelete(m)}
              searchQuery={meetingSearchQuery}
              onSearchChange={setMeetingSearchQuery}
              workflowFilter={workflowModeFilter}
              onWorkflowFilterChange={setWorkflowModeFilter}
              statusFilter={reviewStatusFilter}
              onStatusFilterChange={setReviewStatusFilter}
              onClearFilters={clearMeetingFilters}
            />
          )}

          {/* Page 2: Session Workspace View */}
          {view === 'workspace' && currentPage === 'workspace' && (
            <SessionWorkspaceView
              meetings={meetings}
              selectedMeeting={selectedMeeting}
              onSelectMeeting={handleSelectMeeting}
              onBackToDashboard={() => setCurrentPage('dashboard')}
              minutes={minutes}
              transcript={transcriptForDisplay}
              isProcessing={isProcessing}
              pipelineProgress={pipelineProgress}
              pipelineStage={pipelineStage}
              stageDetail={stageDetail}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              showSpeakersTab={voiceIdEnabled}
              speakersPanel={
                selectedMeeting ? (
                  <SpeakerConfirmationPanel
                    meetingId={selectedMeeting.id}
                    revision={minutes?.revision ?? null}
                    onSeek={handlePlayRange}
                    currentTime={playbackTime}
                    reloadKey={speakersReloadKey}
                    onAttributionChanged={() => {
                      loadMeetingData(selectedMeeting.id);
                      loadMeetings();
                    }}
                  />
                ) : null
              }
              playbackTime={playbackTime}
              setPlaybackTime={setPlaybackTime}
              playbackBucketRef={playbackBucketRef}
              waveformRef={waveformRef}
              onCopyFullMoM={handleCopyFullMoM}
              onDeleteMeeting={(m) => setMeetingToDelete(m)}
              onOpenApproval={() => setIsApprovalOpen(true)}
              onOpenIntake={() => {
                setIntakeInitialMode('upload');
                setIsIntakeOpen(true);
              }}
              isEditingSummary={isEditingSummary}
              setIsEditingSummary={setIsEditingSummary}
              summaryRoEdit={summaryRoEdit}
              setSummaryRoEdit={setSummaryRoEdit}
              summaryEnEdit={summaryEnEdit}
              setSummaryEnEdit={setSummaryEnEdit}
              isSavingMinutes={isSavingMinutes}
              onSaveSummary={handleSaveSummary}
              onUpdateSegment={handleUpdateSegment}
              onSeekAudio={handleSeekAudio}
            />
          )}

          {/* Page 3: Live Meeting Studio */}
          {view === 'workspace' && currentPage === 'live' && (
            <LiveMeetingStudio
              onMeetingRecorded={async (payload, file) => {
                await handleCreateMeeting(payload, file);
                setCurrentPage('workspace');
              }}
              onCancel={() => setCurrentPage('dashboard')}
            />
          )}

          {/* Page 4: Deliveries & Outbox */}
          {view === 'workspace' && currentPage === 'deliveries' && <DeliveriesView />}

          {/* Page 5: System & Settings */}
          {view === 'workspace' && currentPage === 'settings' && <SettingsView />}
        </main>
      </div>

      {/* Delete Confirmation Modal */}
      {meetingToDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4"
          onClick={() => setMeetingToDelete(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-dialog-title"
            onClick={(e) => e.stopPropagation()}
            className="bg-white rounded-2xl shadow-xl border border-slate-200 max-w-md w-full p-6 space-y-4"
          >
            <div className="flex items-center space-x-3 text-rose-600">
              <Trash2 className="w-6 h-6" />
              <h3 id="delete-dialog-title" className="font-bold text-base text-slate-900">
                Delete Meeting Record?
              </h3>
            </div>

            <div className="space-y-3 text-xs text-slate-600 leading-relaxed">
              <p>
                This permanently deletes <strong>"{meetingToDelete.title}"</strong> (
                {new Date(meetingToDelete.scheduled_at).toLocaleDateString()}) from the local vault.
              </p>

              <div className="rounded-xl border border-rose-200 bg-rose-50 p-3">
                <p className="text-[11px] font-bold uppercase tracking-wider text-rose-700">
                  Permanently Removed
                </p>
                <ul className="mt-1 space-y-1 text-xs text-rose-800 font-medium list-disc list-inside">
                  <li>Original audio recording &amp; normalized WAV</li>
                  <li>Full transcript and speaker corrections</li>
                  <li>Official minutes &amp; generated PDF/DOCX revisions</li>
                </ul>
              </div>
            </div>

            <div className="flex items-center justify-end space-x-3 pt-2">
              <button
                ref={deleteCancelRef}
                onClick={() => setMeetingToDelete(null)}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDeleteMeeting(meetingToDelete.id)}
                className="px-4 py-2 text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white rounded-lg shadow-sm transition-colors"
              >
                Delete Permanently
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Dual-Mode Meeting Intake Modal */}
      <MeetingIntakeModal
        isOpen={isIntakeOpen}
        initialMode={intakeInitialMode}
        onClose={() => setIsIntakeOpen(false)}
        onSubmit={handleCreateMeeting}
      />

      {/* Review Approval Modal */}
      {selectedMeeting && (
        <ReviewApprovalModal
          meeting={selectedMeeting}
          isOpen={isApprovalOpen}
          onClose={() => setIsApprovalOpen(false)}
          onApprove={handleApprove}
        />
      )}

      {/* Delivery Outbox Drawer */}
      <DeliveryOutboxDrawer
        isOpen={isOutboxOpen}
        onClose={() => setIsOutboxOpen(false)}
        activeMeetingId={selectedMeetingId || undefined}
      />

      {/* Keyboard Shortcuts Modal */}
      <KeyboardShortcutsModal
        isOpen={isShortcutsOpen}
        onClose={() => setIsShortcutsOpen(false)}
      />
    </div>
  );
};
