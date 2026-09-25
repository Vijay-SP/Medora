import React, { useState, useEffect, useRef } from 'react';
import { Meeting, Transcript, MinutesOfMeeting, MeetingCreate } from './types';
import { apiClient } from './api/client';
import { useToast } from './components/Toast';
import { Navbar } from './components/Navbar';
import { WaveformPlayer, WaveformPlayerRef } from './components/WaveformPlayer';
import { TranscriptViewer } from './components/TranscriptViewer';
import { DecisionsTable } from './components/DecisionsTable';
import { ActionItemsTable } from './components/ActionItemsTable';
import { RisksQuestionsTable } from './components/RisksQuestionsTable';
import { ReviewApprovalModal } from './components/ReviewApprovalModal';
import { MeetingIntakeModal } from './components/MeetingIntakeModal';
import { DeliveryOutboxDrawer } from './components/DeliveryOutboxDrawer';
import { KeyboardShortcutsModal } from './components/KeyboardShortcutsModal';
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
  Search,
  Trash2,
  Copy,
  BarChart2,
  Filter,
} from 'lucide-react';

export const App: React.FC = () => {
  const { showToast } = useToast();

  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState<string | null>(null);
  const [selectedMeeting, setSelectedMeeting] = useState<Meeting | null>(null);

  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [minutes, setMinutes] = useState<MinutesOfMeeting | null>(null);

  const [activeTab, setActiveTab] = useState<'minutes' | 'transcript'>('minutes');
  const [playbackTime, setPlaybackTime] = useState<number>(0);

  // Meeting Search & Filter
  const [meetingSearchQuery, setMeetingSearchQuery] = useState('');
  const [workflowModeFilter, setWorkflowModeFilter] = useState<string>('all');
  const [reviewStatusFilter, setReviewStatusFilter] = useState<string>('all');

  // Modals & Drawers
  const [isIntakeOpen, setIsIntakeOpen] = useState(false);
  const [isApprovalOpen, setIsApprovalOpen] = useState(false);
  const [isOutboxOpen, setIsOutboxOpen] = useState(false);
  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);
  const [meetingToDelete, setMeetingToDelete] = useState<Meeting | null>(null);

  // Minutes Editing State
  const [isEditingSummary, setIsEditingSummary] = useState(false);
  const [summaryRoEdit, setSummaryRoEdit] = useState('');
  const [summaryEnEdit, setSummaryEnEdit] = useState('');
  const [isSavingMinutes, setIsSavingMinutes] = useState(false);

  // Loading & Processing state
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [pipelineProgress, setPipelineProgress] = useState(0);
  const [stageDetail, setStageDetail] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const waveformRef = useRef<WaveformPlayerRef>(null);
  const selectedMeetingIdRef = useRef<string | null>(selectedMeetingId);

  useEffect(() => {
    selectedMeetingIdRef.current = selectedMeetingId;
  }, [selectedMeetingId]);

  // Initial load
  useEffect(() => {
    loadMeetings();
  }, []);

  // Poll meeting detail when selected
  useEffect(() => {
    if (selectedMeetingId) {
      loadMeetingData(selectedMeetingId);
    }
  }, [selectedMeetingId]);

  // Polling pipeline status if processing
  useEffect(() => {
    let interval: number | null = null;
    if (isProcessing && selectedMeetingId) {
      interval = window.setInterval(async () => {
        try {
          const status = await apiClient.getPipelineStatus(selectedMeetingId);
          setPipelineProgress(status.progress);
          setStageDetail(status.current_stage || '');

          if (status.status === 'completed' || status.status === 'failed') {
            setIsProcessing(false);
            if (interval) clearInterval(interval);
            loadMeetingData(selectedMeetingId);
            loadMeetings();
          }
        } catch (err) {
          console.error('Error polling pipeline status:', err);
        }
      }, 1500);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isProcessing, selectedMeetingId]);

  // Global Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeTag = document.activeElement?.tagName;
      if (activeTag === 'INPUT' || activeTag === 'TEXTAREA' || activeTag === 'SELECT') {
        return;
      }

      if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault();
        waveformRef.current?.togglePlay();
      } else if (e.key === '?') {
        e.preventDefault();
        setIsShortcutsOpen((prev) => !prev);
      } else if (e.key === 'm' || e.key === 'M') {
        e.preventDefault();
        setIsIntakeOpen(true);
      } else if (e.key === 'o' || e.key === 'O') {
        e.preventDefault();
        setIsOutboxOpen(true);
      } else if (e.key === '1') {
        setActiveTab('minutes');
      } else if (e.key === '2') {
        setActiveTab('transcript');
      } else if (e.key === 'Escape') {
        setIsIntakeOpen(false);
        setIsApprovalOpen(false);
        setIsOutboxOpen(false);
        setIsShortcutsOpen(false);
        setMeetingToDelete(null);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

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
        setIsProcessing(true);
        setPipelineProgress(m.processing_progress);
        setStageDetail(m.current_stage_detail || '');
      } else {
        setIsProcessing(false);
      }

      // Load transcript
      try {
        const t = await apiClient.getTranscript(id);
        if (selectedMeetingIdRef.current === id) {
          setTranscript(t);
        }
      } catch {
        if (selectedMeetingIdRef.current === id) setTranscript(null);
      }

      // Load minutes
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
    try {
      const created = await apiClient.createMeeting(payload);
      if (file) {
        await apiClient.uploadAudio(created.id, file);
        await apiClient.startPipeline(created.id);
        setIsProcessing(true);
        setPipelineProgress(5);
        setStageDetail('Initializing pipeline...');
      }
      showToast('Meeting created', `Meeting "${created.title}" successfully recorded and pipeline started.`);
      await loadMeetings();
      setSelectedMeetingId(created.id);
    } catch (err: any) {
      console.error('Error creating meeting:', err);
      setErrorMessage(`Failed to create meeting: ${err?.message || 'Server error'}`);
      showToast('Creation failed', err?.message || 'Server error', 'error');
    }
  };

  const handleDeleteMeeting = async (id: string) => {
    try {
      await apiClient.deleteMeeting(id);
      showToast('Meeting deleted', 'Meeting record removed successfully.');
      setMeetingToDelete(null);
      const remaining = meetings.filter((m) => m.id !== id);
      setMeetings(remaining);
      if (selectedMeetingId === id) {
        setSelectedMeetingId(remaining.length > 0 ? remaining[0].id : null);
        setSelectedMeeting(remaining.length > 0 ? remaining[0] : null);
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
      showToast('Summary saved', `Updated executive summary saved for Revision ${updated.revision}.`);
      await loadMeetingData(selectedMeetingId);
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
    const updated = await apiClient.getTranscript(selectedMeetingId);
    setTranscript(updated);
  };

  const handleApprove = async (reviewerName: string, reviewerRole: string, comments: string) => {
    if (!selectedMeetingId) return;
    setErrorMessage(null);
    try {
      await apiClient.approveMeeting(selectedMeetingId, {
        reviewer_name: reviewerName,
        reviewer_role: reviewerRole,
        comments,
      });
      showToast('Minutes Approved & Dispatched', 'Signed official minutes dispatched to hospital distribution list.');
      await loadMeetingData(selectedMeetingId);
      await loadMeetings();
    } catch (err: any) {
      setErrorMessage(`Failed to approve meeting: ${err?.message || 'Server error'}`);
      showToast('Approval failed', err?.message || 'Server error', 'error');
    }
  };

  const handleSeekAudio = (startSec: number, endSec?: number) => {
    if (waveformRef.current) {
      if (endSec !== undefined && endSec > startSec) {
        waveformRef.current.playRange(startSec, endSec);
      } else {
        waveformRef.current.seekToSeconds(startSec);
      }
    }
  };

  const handleCopyFullMoM = () => {
    if (!minutes || !selectedMeeting) return;
    const text = `# ${selectedMeeting.title}
**Meeting Type:** ${selectedMeeting.meeting_type.toUpperCase()} | **Date:** ${new Date(selectedMeeting.scheduled_at).toLocaleString()}
**Attendees:** ${selectedMeeting.attendees.map((a) => a.name).join(', ')}

## Executive Summary
${minutes.summary_ro}
${minutes.summary_en ? `\n[English Summary]: ${minutes.summary_en}` : ''}

## Decisions (${minutes.decisions.length})
${minutes.decisions.map((d, i) => `${i + 1}. [${d.category.toUpperCase()}] ${d.topic}: ${d.decision}`).join('\n')}

## Action Items (${minutes.action_items.length})
${minutes.action_items.map((a, i) => `${i + 1}. [${a.priority.toUpperCase()}] Owner: ${a.owner} | Task: ${a.task} | Deadline: ${a.deadline_date || a.deadline_phrase || 'N/A'}`).join('\n')}
`;

    navigator.clipboard.writeText(text);
    showToast('Copied Full Minutes', 'Executive summary, decisions, and action items copied as Markdown.');
  };

  // Filter meetings list
  const filteredMeetings = meetings.filter((m) => {
    if (workflowModeFilter !== 'all' && m.workflow_mode !== workflowModeFilter) return false;
    if (reviewStatusFilter !== 'all' && m.review_status !== reviewStatusFilter) return false;
    if (meetingSearchQuery.trim()) {
      const q = meetingSearchQuery.toLowerCase();
      return m.title.toLowerCase().includes(q) || m.meeting_type.toLowerCase().includes(q);
    }
    return true;
  });

  // Calculate meeting stats
  const totalCount = meetings.length;
  const pendingCount = meetings.filter((m) => m.review_status === 'pending_review' || m.review_status === 'draft').length;
  const deliveredCount = meetings.filter((m) => m.review_status === 'delivered').length;

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans text-slate-800">
      <Navbar
        onNewMeeting={() => setIsIntakeOpen(true)}
        onOpenDeliveries={() => setIsOutboxOpen(true)}
        onOpenShortcuts={() => setIsShortcutsOpen(true)}
        meetingsCount={meetings.length}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        
        {/* Error Notification Banner */}
        {errorMessage && (
          <div className="bg-rose-50 border border-rose-200 text-rose-800 p-4 rounded-xl flex items-center justify-between shadow-xs">
            <div className="flex items-center space-x-2">
              <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />
              <span className="text-xs font-semibold">{errorMessage}</span>
            </div>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-xs font-bold px-2.5 py-1 bg-white border border-rose-200 rounded-md text-rose-700 hover:bg-rose-100 transition-colors"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Executive Stats & Meeting Filter Bar */}
        <div className="bg-white p-4 sm:p-5 rounded-2xl border border-slate-200 shadow-xs space-y-4">
          {/* Summary Stats Badges */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-100">
            <div className="flex items-center space-x-2 text-xs font-bold text-slate-700">
              <BarChart2 className="w-4 h-4 text-medpark-600" />
              <span>Hospital Meeting Repository</span>
            </div>

            <div className="flex items-center space-x-3 text-xs">
              <span className="px-3 py-1 bg-slate-100 text-slate-700 rounded-full font-bold border border-slate-200">
                Total: {totalCount}
              </span>
              <span className="px-3 py-1 bg-amber-50 text-amber-800 rounded-full font-bold border border-amber-200">
                Pending Review: {pendingCount}
              </span>
              <span className="px-3 py-1 bg-emerald-50 text-emerald-800 rounded-full font-bold border border-emerald-200">
                Delivered: {deliveredCount}
              </span>
            </div>
          </div>

          {/* Meeting Switcher & Filter Controls */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
            {/* Search Input */}
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                value={meetingSearchQuery}
                onChange={(e) => setMeetingSearchQuery(e.target.value)}
                placeholder="Search meeting titles..."
                className="w-full text-xs pl-9 pr-3 py-2 rounded-lg border border-slate-300 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              />
            </div>

            {/* Workflow & Status Dropdowns */}
            <div className="flex items-center space-x-2">
              <div className="flex items-center space-x-1 bg-slate-50 p-1 rounded-lg border border-slate-200 text-xs">
                <Filter className="w-3.5 h-3.5 text-slate-400 ml-1.5" />
                <select
                  value={workflowModeFilter}
                  onChange={(e) => setWorkflowModeFilter(e.target.value)}
                  className="bg-transparent text-xs font-medium text-slate-700 focus:outline-none cursor-pointer"
                >
                  <option value="all">All Modes</option>
                  <option value="supervised">Supervised</option>
                  <option value="auto_pilot">Auto-Pilot</option>
                </select>
              </div>

              <div className="flex items-center space-x-1 bg-slate-50 p-1 rounded-lg border border-slate-200 text-xs">
                <select
                  value={reviewStatusFilter}
                  onChange={(e) => setReviewStatusFilter(e.target.value)}
                  className="bg-transparent text-xs font-medium text-slate-700 focus:outline-none cursor-pointer"
                >
                  <option value="all">All Statuses</option>
                  <option value="pending_review">Pending Review</option>
                  <option value="delivered">Delivered</option>
                  <option value="draft">Draft</option>
                </select>
              </div>
            </div>
          </div>

          {/* Horizontal Meeting List Buttons */}
          <div className="flex items-center space-x-2 overflow-x-auto pb-1 pt-1">
            {filteredMeetings.map((m) => (
              <button
                key={m.id}
                onClick={() => handleSelectMeeting(m.id)}
                className={`px-3 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all border flex items-center space-x-2 ${
                  selectedMeetingId === m.id
                    ? 'bg-medpark-500 text-white border-medpark-600 shadow-xs'
                    : 'bg-slate-50 text-slate-700 hover:bg-slate-100 border-slate-200'
                }`}
              >
                <span>{m.title}</span>
                {m.review_status === 'delivered' && (
                  <CheckCircle2 className={`w-3.5 h-3.5 ${selectedMeetingId === m.id ? 'text-white' : 'text-emerald-600'}`} />
                )}
              </button>
            ))}

            {filteredMeetings.length === 0 && !isLoading && (
              <span className="text-xs text-slate-400 font-medium py-1">
                No meetings match the search filter.
              </span>
            )}
          </div>
        </div>

        {/* Live Processing Banner */}
        {isProcessing && (
          <div className="bg-gradient-to-r from-blue-600 to-medpark-600 text-white p-5 rounded-2xl shadow-md space-y-3 animate-in fade-in duration-200">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <Loader2 className="w-5 h-5 animate-spin" />
                <h4 className="font-bold text-sm tracking-wide">
                  Intelligent Pipeline Processing (100% Air-Gapped)
                </h4>
              </div>
              <span className="font-mono text-sm font-bold bg-white/20 px-2 py-0.5 rounded">
                {pipelineProgress}%
              </span>
            </div>

            <div className="w-full bg-black/20 rounded-full h-2 overflow-hidden">
              <div
                className="bg-white h-2 rounded-full transition-all duration-300"
                style={{ width: `${pipelineProgress}%` }}
              />
            </div>

            <p className="text-xs text-blue-100 flex items-center space-x-1.5 font-medium">
              <span>{stageDetail || 'Processing audio normalization, VAD chunking, ASR, and extraction...'}</span>
            </p>
          </div>
        )}

        {/* Selected Meeting Workspace */}
        {selectedMeeting && (
          <div className="space-y-6">
            
            {/* Meeting Meta Header */}
            <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-xs flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              <div className="space-y-1.5">
                <div className="flex flex-wrap items-center gap-2.5">
                  <h2 className="text-xl font-black text-slate-900 tracking-tight">
                    {selectedMeeting.title}
                  </h2>
                  <span className="text-xs font-bold uppercase px-2.5 py-0.5 rounded-md bg-medpark-50 text-medpark-700 border border-medpark-200">
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
                        <Rocket className="w-3.5 h-3.5" />
                        <span>Auto-Pilot (Zero-Click)</span>
                      </>
                    ) : (
                      <>
                        <Shield className="w-3.5 h-3.5" />
                        <span>Supervised (Clinical Gate)</span>
                      </>
                    )}
                  </span>

                  {selectedMeeting.review_status === 'delivered' && (
                    <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-md text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                      <span>Delivered via Email</span>
                    </span>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 font-medium pt-1">
                  <span className="flex items-center space-x-1">
                    <Calendar className="w-3.5 h-3.5 text-slate-400" />
                    <span>{new Date(selectedMeeting.scheduled_at).toLocaleString()}</span>
                  </span>
                  <span className="flex items-center space-x-1">
                    <Clock className="w-3.5 h-3.5 text-slate-400" />
                    <span>Audio: {selectedMeeting.audio_duration_seconds.toFixed(1)}s</span>
                  </span>
                  <span className="flex items-center space-x-1">
                    <Users className="w-3.5 h-3.5 text-slate-400" />
                    <span>{selectedMeeting.attendees.length} participants</span>
                  </span>
                  {selectedMeeting.processing_time_seconds > 0 && (
                    <span className="flex items-center space-x-1 font-mono text-emerald-600 font-bold">
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Pipeline: {selectedMeeting.processing_time_seconds}s</span>
                    </span>
                  )}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap items-center gap-2">
                {/* Copy Full MoM */}
                {minutes && (
                  <button
                    onClick={handleCopyFullMoM}
                    className="inline-flex items-center space-x-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-lg transition-colors"
                    title="Copy executive summary, decisions, and action items"
                  >
                    <Copy className="w-3.5 h-3.5 text-slate-500" />
                    <span>Copy Full MoM</span>
                  </button>
                )}

                {/* Download PDF/DOCX */}
                {minutes && (
                  <>
                    <a
                      href={apiClient.getPdfDownloadUrl(selectedMeeting.id)}
                      download
                      className="inline-flex items-center space-x-1.5 px-3 py-2 bg-rose-50 hover:bg-rose-100 text-rose-800 border border-rose-200 text-xs font-bold rounded-lg transition-colors"
                      title="Download official PDF report"
                    >
                      <FileDown className="w-3.5 h-3.5 text-rose-600" />
                      <span>PDF</span>
                    </a>

                    <a
                      href={apiClient.getDocxDownloadUrl(selectedMeeting.id)}
                      download
                      className="inline-flex items-center space-x-1.5 px-3 py-2 bg-blue-50 hover:bg-blue-100 text-blue-800 border border-blue-200 text-xs font-bold rounded-lg transition-colors"
                      title="Download official Word DOCX report"
                    >
                      <FileDown className="w-3.5 h-3.5 text-blue-600" />
                      <span>DOCX</span>
                    </a>
                  </>
                )}

                {/* Approve Button in Supervised Mode */}
                {selectedMeeting.workflow_mode === 'supervised' &&
                  selectedMeeting.review_status !== 'delivered' && (
                    <button
                      onClick={() => setIsApprovalOpen(true)}
                      className="inline-flex items-center space-x-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold rounded-lg shadow-sm transition-all"
                    >
                      <Shield className="w-3.5 h-3.5" />
                      <span>Sign & Dispatch</span>
                    </button>
                  )}

                {/* Delete Meeting Button */}
                <button
                  onClick={() => setMeetingToDelete(selectedMeeting)}
                  className="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
                  title="Delete meeting record"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* WaveSurfer Audio Player */}
            {selectedMeeting.original_audio_path && (
              <WaveformPlayer
                ref={waveformRef}
                audioUrl={apiClient.getAudioStreamUrl(selectedMeeting.id)}
                onTimeUpdate={(t) => setPlaybackTime(t)}
              />
            )}

            {/* Tabs Navigation */}
            <div className="border-b border-slate-200 flex space-x-6">
              <button
                onClick={() => setActiveTab('minutes')}
                className={`pb-3 text-sm font-bold flex items-center space-x-2 border-b-2 transition-all ${
                  activeTab === 'minutes'
                    ? 'border-medpark-500 text-medpark-600'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <FileText className="w-4 h-4" />
                <span>Official Minutes (MoM)</span>
              </button>

              <button
                onClick={() => setActiveTab('transcript')}
                className={`pb-3 text-sm font-bold flex items-center space-x-2 border-b-2 transition-all ${
                  activeTab === 'transcript'
                    ? 'border-medpark-500 text-medpark-600'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <Layers className="w-4 h-4" />
                <span>Multilingual Transcript & Speakers</span>
                {transcript && (
                  <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full font-bold">
                    {transcript.segments.length}
                  </span>
                )}
              </button>
            </div>

            {/* Tab 1: Minutes Workspace */}
            {activeTab === 'minutes' && (
              <div className="space-y-6">
                {minutes ? (
                  <>
                    {/* Executive Summary & Revision Meta */}
                    <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-xs space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                          <Sparkles className="w-4 h-4 text-medpark-600" />
                          <h3 className="font-bold text-sm text-slate-900">Medpark Executive Summary</h3>
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                            Revision {minutes.revision}
                          </span>
                          <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
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
                              onClick={handleSaveSummary}
                              disabled={isSavingMinutes}
                              className="inline-flex items-center space-x-1 text-xs bg-medpark-500 hover:bg-medpark-600 text-white font-bold px-3 py-1 rounded-md shadow-2xs transition-colors disabled:opacity-50"
                            >
                              {isSavingMinutes ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
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
                    <DecisionsTable
                      decisions={minutes.decisions}
                      onSeek={handleSeekAudio}
                    />

                    {/* Action Items Table */}
                    <ActionItemsTable
                      actionItems={minutes.action_items}
                      onSeek={handleSeekAudio}
                    />

                    {/* Risks and Unresolved Questions Table */}
                    <RisksQuestionsTable
                      items={minutes.risks_and_questions || []}
                      onSeek={handleSeekAudio}
                    />
                  </>
                ) : (
                  <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center text-slate-400 text-sm font-medium">
                    {isProcessing
                      ? 'Minutes of meeting are currently being extracted...'
                      : 'No minutes generated yet. Upload an audio file to trigger the pipeline.'}
                  </div>
                )}
              </div>
            )}

            {/* Tab 2: Multilingual Transcript */}
            {activeTab === 'transcript' && (
              <div>
                {transcript ? (
                  <TranscriptViewer
                    segments={transcript.segments}
                    onSeek={handleSeekAudio}
                    onUpdateSegment={handleUpdateSegment}
                    currentTime={playbackTime}
                  />
                ) : (
                  <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center text-slate-400 text-sm font-medium">
                    {isProcessing
                      ? 'Generating multilingual transcript...'
                      : 'Transcript is not yet available.'}
                  </div>
                )}
              </div>
            )}

          </div>
        )}

      </main>

      {/* Delete Confirmation Modal */}
      {meetingToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 max-w-md w-full p-6 space-y-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center space-x-3 text-rose-600">
              <Trash2 className="w-6 h-6" />
              <h3 className="font-bold text-base text-slate-900">Delete Meeting Record?</h3>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              Are you sure you want to permanently delete <strong>"{meetingToDelete.title}"</strong> and all associated transcript/document artifacts? This action cannot be undone.
            </p>
            <div className="flex items-center justify-end space-x-3 pt-2">
              <button
                onClick={() => setMeetingToDelete(null)}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDeleteMeeting(meetingToDelete.id)}
                className="px-4 py-2 text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white rounded-lg shadow-2xs transition-all"
              >
                Delete Permanently
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modals & Drawers */}
      <MeetingIntakeModal
        isOpen={isIntakeOpen}
        onClose={() => setIsIntakeOpen(false)}
        onSubmit={handleCreateMeeting}
      />

      {selectedMeeting && (
        <ReviewApprovalModal
          meeting={selectedMeeting}
          isOpen={isApprovalOpen}
          onClose={() => setIsApprovalOpen(false)}
          onApprove={handleApprove}
        />
      )}

      <DeliveryOutboxDrawer
        isOpen={isOutboxOpen}
        onClose={() => setIsOutboxOpen(false)}
        activeMeetingId={selectedMeetingId || undefined}
      />

      <KeyboardShortcutsModal
        isOpen={isShortcutsOpen}
        onClose={() => setIsShortcutsOpen(false)}
      />
    </div>
  );
};
