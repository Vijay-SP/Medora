import React, { useState, useEffect, useRef } from 'react';
import { Meeting, Transcript, MinutesOfMeeting, MeetingCreate } from './types';
import { apiClient } from './api/client';
import { Navbar } from './components/Navbar';
import { WaveformPlayer, WaveformPlayerRef } from './components/WaveformPlayer';
import { TranscriptViewer } from './components/TranscriptViewer';
import { DecisionsTable } from './components/DecisionsTable';
import { ActionItemsTable } from './components/ActionItemsTable';
import { RisksQuestionsTable } from './components/RisksQuestionsTable';
import { ReviewApprovalModal } from './components/ReviewApprovalModal';
import { MeetingIntakeModal } from './components/MeetingIntakeModal';
import { DeliveryOutboxDrawer } from './components/DeliveryOutboxDrawer';
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
} from 'lucide-react';

export const App: React.FC = () => {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState<string | null>(null);
  const [selectedMeeting, setSelectedMeeting] = useState<Meeting | null>(null);

  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [minutes, setMinutes] = useState<MinutesOfMeeting | null>(null);

  const [activeTab, setActiveTab] = useState<'minutes' | 'transcript'>('minutes');

  // Modals
  const [isIntakeOpen, setIsIntakeOpen] = useState(false);
  const [isApprovalOpen, setIsApprovalOpen] = useState(false);
  const [isOutboxOpen, setIsOutboxOpen] = useState(false);

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

      // Load transcript if exists
      try {
        const t = await apiClient.getTranscript(id);
        if (selectedMeetingIdRef.current === id) {
          setTranscript(t);
        }
      } catch {
        if (selectedMeetingIdRef.current === id) setTranscript(null);
      }

      // Load minutes if exists
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
        // Automatically start processing
        await apiClient.startPipeline(created.id);
        setIsProcessing(true);
        setPipelineProgress(5);
        setStageDetail('Initializing processing...');
      }
      await loadMeetings();
      setSelectedMeetingId(created.id);
    } catch (err: any) {
      console.error('Error creating meeting:', err);
      setErrorMessage(`Failed to create meeting: ${err?.message || 'Server processing error'}`);
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
      await loadMeetingData(selectedMeetingId);
    } catch (err: any) {
      console.error('Failed to update minutes:', err);
      setErrorMessage(`Failed to update summary: ${err?.message || 'Server error'}`);
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
      await loadMeetingData(selectedMeetingId);
      await loadMeetings();
    } catch (err: any) {
      setErrorMessage(`Failed to approve meeting: ${err?.message || 'Server error'}`);
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

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      <Navbar
        onNewMeeting={() => setIsIntakeOpen(true)}
        onOpenDeliveries={() => setIsOutboxOpen(true)}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        
        {/* Error Notification Banner */}
        {errorMessage && (
          <div className="bg-rose-50 border border-rose-200 text-rose-800 p-4 rounded-xl flex items-center justify-between shadow-xs">
            <div className="flex items-center space-x-2">
              <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />
              <span className="text-sm font-medium">{errorMessage}</span>
            </div>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-xs font-semibold px-2.5 py-1 bg-white border border-rose-200 rounded-md text-rose-700 hover:bg-rose-100 transition-colors"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Top Controls / Meeting Selector Strip */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
          <div className="flex items-center space-x-3 overflow-x-auto pb-1 md:pb-0">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Meeting:</span>
            {meetings.map((m) => (
              <button
                key={m.id}
                onClick={() => handleSelectMeeting(m.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                  selectedMeetingId === m.id
                    ? 'bg-medpark-500 text-white shadow-xs'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200/80'
                }`}
              >
                {m.title}
              </button>
            ))}

            {meetings.length === 0 && !isLoading && (
              <span className="text-xs text-slate-400">No meetings recorded.</span>
            )}
          </div>

          {selectedMeeting && (
            <div className="flex items-center space-x-2 text-xs">
              <span
                className={`inline-flex items-center space-x-1 px-2.5 py-1 rounded-full font-semibold border ${
                  selectedMeeting.workflow_mode === 'auto_pilot'
                    ? 'bg-blue-50 text-blue-700 border-blue-200'
                    : 'bg-emerald-50 text-emerald-700 border-emerald-200'
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
                <span className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full font-semibold bg-emerald-100 text-emerald-800">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Delivered via Email</span>
                </span>
              )}
            </div>
          )}
        </div>

        {/* Live Processing Banner */}
        {isProcessing && (
          <div className="bg-gradient-to-r from-blue-600 to-medpark-600 text-white p-5 rounded-2xl shadow-md space-y-3 animate-in fade-in duration-200">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <Loader2 className="w-5 h-5 animate-spin" />
                <h4 className="font-bold text-sm tracking-wide">
                  Intelligent Pipeline in Progress (100% Offline)
                </h4>
              </div>
              <span className="font-mono text-sm font-bold bg-white/20 px-2 py-0.5 rounded">
                {pipelineProgress}%
              </span>
            </div>

            {/* Progress Bar */}
            <div className="w-full bg-black/20 rounded-full h-2 overflow-hidden">
              <div
                className="bg-white h-2 rounded-full transition-all duration-300"
                style={{ width: `${pipelineProgress}%` }}
              />
            </div>

            <p className="text-xs text-blue-100 flex items-center space-x-1.5 font-medium">
              <span>{stageDetail || 'Processing audio and extraction stages...'}</span>
            </p>
          </div>
        )}

        {/* Selected Meeting Workspace */}
        {selectedMeeting && (
          <div className="space-y-6">
            
            {/* Meeting Meta Header */}
            <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-1.5">
                <div className="flex items-center space-x-2.5">
                  <h2 className="text-xl font-bold text-slate-900 tracking-tight">
                    {selectedMeeting.title}
                  </h2>
                  <span className="text-xs font-bold uppercase px-2 py-0.5 rounded bg-medpark-50 text-medpark-700 border border-medpark-200">
                    {selectedMeeting.meeting_type}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 font-medium pt-1">
                  <span className="flex items-center space-x-1">
                    <Calendar className="w-3.5 h-3.5 text-slate-400" />
                    <span>{new Date(selectedMeeting.scheduled_at).toLocaleString()}</span>
                  </span>
                  <span className="flex items-center space-x-1">
                    <Clock className="w-3.5 h-3.5 text-slate-400" />
                    <span>Audio Duration: {selectedMeeting.audio_duration_seconds.toFixed(1)}s</span>
                  </span>
                  <span className="flex items-center space-x-1">
                    <Users className="w-3.5 h-3.5 text-slate-400" />
                    <span>{selectedMeeting.attendees.length} participants</span>
                  </span>
                  {selectedMeeting.processing_time_seconds > 0 && (
                    <span className="flex items-center space-x-1 font-mono text-emerald-600 font-semibold">
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Processing Time: {selectedMeeting.processing_time_seconds}s</span>
                    </span>
                  )}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap items-center gap-2">
                {/* Download PDF/DOCX */}
                {minutes && (
                  <>
                    <a
                      href={apiClient.getPdfDownloadUrl(selectedMeeting.id)}
                      download
                      className="inline-flex items-center space-x-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-lg transition-colors"
                      title="Download official minutes in PDF format"
                    >
                      <FileDown className="w-3.5 h-3.5 text-rose-600" />
                      <span>PDF</span>
                    </a>

                    <a
                      href={apiClient.getDocxDownloadUrl(selectedMeeting.id)}
                      download
                      className="inline-flex items-center space-x-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-lg transition-colors"
                      title="Download official minutes in Word DOCX format"
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
                      className="inline-flex items-center space-x-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-all"
                    >
                      <Shield className="w-3.5 h-3.5" />
                      <span>Sign & Dispatch</span>
                    </button>
                  )}
              </div>
            </div>

            {/* WaveSurfer Audio Player */}
            {selectedMeeting.original_audio_path && (
              <WaveformPlayer
                ref={waveformRef}
                audioUrl={apiClient.getAudioStreamUrl(selectedMeeting.id)}
              />
            )}

            {/* Tabs Navigation */}
            <div className="border-b border-slate-200 flex space-x-6">
              <button
                onClick={() => setActiveTab('minutes')}
                className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition-all ${
                  activeTab === 'minutes'
                    ? 'border-medpark-500 text-medpark-600'
                    : 'border-transparent text-slate-500 hover:text-slate-700'
                }`}
              >
                <FileText className="w-4 h-4" />
                <span>Official Minutes (MoM)</span>
              </button>

              <button
                onClick={() => setActiveTab('transcript')}
                className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition-all ${
                  activeTab === 'transcript'
                    ? 'border-medpark-500 text-medpark-600'
                    : 'border-transparent text-slate-500 hover:text-slate-700'
                }`}
              >
                <Layers className="w-4 h-4" />
                <span>Multilingual Transcript & Speakers</span>
                {transcript && (
                  <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full">
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
                    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                          <Sparkles className="w-4 h-4 text-medpark-600" />
                          <h3 className="font-semibold text-sm text-slate-900">Medpark Executive Summary</h3>
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
                            className="inline-flex items-center space-x-1.5 text-xs text-slate-600 hover:text-medpark-600 hover:bg-slate-50 px-2.5 py-1 rounded-md border border-slate-200 transition-colors"
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
                              className="inline-flex items-center space-x-1 text-xs bg-medpark-500 hover:bg-medpark-600 text-white font-medium px-3 py-1 rounded-md shadow-xs transition-colors disabled:opacity-50"
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
                          <p className="text-sm text-slate-700 leading-relaxed">{minutes.summary_ro}</p>
                          {minutes.summary_en && (
                            <p className="text-xs text-slate-500 italic pt-1 border-t border-slate-100">
                              <span className="font-semibold text-slate-600 not-italic mr-1">[English Summary]</span>
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
                              className="text-xs font-medium bg-slate-100 text-slate-700 px-2.5 py-1 rounded-md border border-slate-200"
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
                  <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-400 text-sm">
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
                  />
                ) : (
                  <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-400 text-sm">
                    {isProcessing
                      ? 'Generating multilingual transcription...'
                      : 'Transcript is not yet available.'}
                  </div>
                )}
              </div>
            )}

          </div>
        )}

      </main>

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
    </div>
  );
};
