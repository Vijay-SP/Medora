import React, { useState, useEffect, useRef } from 'react';
import { MeetingCreate, MeetingType, WorkflowMode, Attendee } from '../types';
import { AudioRecorder } from './AudioRecorder';
import { UploadCloud, FileAudio, Users, Sparkles, X, Plus, Trash2, Rocket, Shield, AlertTriangle, Mic, Radio } from 'lucide-react';
import { ParticipantSelector } from './ParticipantSelector';

// Mirrors FileManager.ALLOWED_AUDIO_EXTENSIONS so the rejection happens before upload.
const ALLOWED_AUDIO_EXTENSIONS = ['.wav', '.mp3', '.m4a', '.webm', '.ogg', '.aac', '.flac', '.mp4'];

interface MeetingIntakeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (meetingData: MeetingCreate, audioFile?: File) => Promise<void>;
  initialMode?: 'upload' | 'live';
}

export const MeetingIntakeModal: React.FC<MeetingIntakeModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  initialMode = 'upload',
}) => {
  const [intakeMode, setIntakeMode] = useState<'upload' | 'live'>(initialMode);
  const [title, setTitle] = useState('');
  const [meetingType, setMeetingType] = useState<MeetingType>('medical');
  const [workflowMode, setWorkflowMode] = useState<WorkflowMode>('supervised');
  const [agenda, setAgenda] = useState('');
  const [audioFile, setAudioFile] = useState<File | null>(null);
  
  // Meeting attendees
  const [attendees, setAttendees] = useState<Attendee[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [titleError, setTitleError] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [hasEntered, setHasEntered] = useState(false);

  const panelRef = useRef<HTMLDivElement>(null);

  // Enter transition built from core Tailwind utilities (no animation plugin is installed):
  // the card is painted once in its "from" state, then transitions in. Under
  // prefers-reduced-motion the motion-safe: from-state never applies, so it just appears.
  useEffect(() => {
    if (!isOpen) {
      setHasEntered(false);
      return;
    }
    setIntakeMode(initialMode);
    const frame = requestAnimationFrame(() => setHasEntered(true));
    return () => cancelAnimationFrame(frame);
  }, [isOpen, initialMode]);

  // Move focus into the dialog, keep Tab inside it, and hand focus back on close.
  useEffect(() => {
    if (!isOpen) return;
    const panel = panelRef.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const initial = panel?.querySelector<HTMLElement>('[data-autofocus]') || panel;
    initial?.focus();

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !panel) return;
      const focusables = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
        e.preventDefault();
        last.focus();
      }
    };

    document.addEventListener('keydown', handleTab);
    return () => {
      document.removeEventListener('keydown', handleTab);
      previouslyFocused?.focus?.();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const isDirty = Boolean(title.trim() || agenda.trim() || audioFile || attendees.length > 0);

  const handleSelectAudioFile = (file: File) => {
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!ALLOWED_AUDIO_EXTENSIONS.includes(ext)) {
      setAudioFile(null);
      setAudioError(`"${ext || file.name}" is not a supported audio format. Allowed: ${ALLOWED_AUDIO_EXTENSIONS.join(', ')}.`);
      return;
    }
    setAudioError(null);
    setAudioFile(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setTitleError('A meeting title is required.');
      panelRef.current?.querySelector<HTMLInputElement>('#intake-title-field')?.focus();
      return;
    }
    setTitleError(null);

    setIsSubmitting(true);
    try {
      const payload: MeetingCreate = {
        title: title.trim(),
        meeting_type: meetingType,
        workflow_mode: workflowMode,
        scheduled_at: new Date().toISOString(),
        attendees,
        agenda: agenda.trim() || undefined,
        distribution_list: [],
      };
      await onSubmit(payload, audioFile || undefined);
      onClose();
    } catch (err) {
      console.error('Failed to create meeting:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  // A stray backdrop click must never silently discard a partly filled intake form.
  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || isDirty) return;
    onClose();
  };

  return (
    <div
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/50 backdrop-blur-sm p-4 overflow-y-auto"
    >
      {/* items-start + my-auto keeps the card centred when it fits and pinned to the scroll
          origin when it is taller than the viewport, so the header and X stay reachable. */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="intake-title"
        tabIndex={-1}
        className={`bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-2xl overflow-hidden my-auto focus:outline-none transition duration-150 ease-out motion-reduce:transition-none ${
          hasEntered ? 'opacity-100 scale-100' : 'motion-safe:opacity-0 motion-safe:scale-95'
        }`}
      >

        {/* Header */}
        <div className="p-5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div>
            <h3 id="intake-title" className="font-bold text-slate-900 text-base">New Meeting</h3>
            <p className="text-xs text-slate-500">Medora • 100% Offline Clinical Meeting Intelligence</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close intake dialog"
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Mode Selector: Live Meeting vs Upload Recorded Meeting */}
          <div className="grid grid-cols-2 p-1 bg-slate-100 rounded-xl gap-1">
            <button
              type="button"
              onClick={() => setIntakeMode('live')}
              className={`flex items-center justify-center space-x-2 py-2.5 rounded-lg text-xs font-bold transition-all ${
                intakeMode === 'live'
                  ? 'bg-rose-600 text-white shadow-sm'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50'
              }`}
            >
              <Mic className="w-4 h-4" />
              <span>Start Live Meeting</span>
            </button>
            <button
              type="button"
              onClick={() => setIntakeMode('upload')}
              className={`flex items-center justify-center space-x-2 py-2.5 rounded-lg text-xs font-bold transition-all ${
                intakeMode === 'upload'
                  ? 'bg-medpark-500 text-white shadow-sm'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200/50'
              }`}
            >
              <UploadCloud className="w-4 h-4" />
              <span>Upload Recorded Meeting</span>
            </button>
          </div>

          {/* Title */}
          <div className="space-y-1.5">
            <label htmlFor="intake-title-field" className="text-xs font-semibold text-slate-700">
              Meeting Title <span className="text-rose-600" aria-hidden="true">*</span>
            </label>
            <input
              id="intake-title-field"
              type="text"
              required
              aria-required="true"
              aria-invalid={titleError ? true : undefined}
              aria-describedby={titleError ? 'intake-title-error' : undefined}
              data-autofocus
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                if (titleError) setTitleError(null);
              }}
              placeholder="e.g., Medical Board - ICU Protocols & Cardiology Cases"
              className={`w-full text-sm px-3.5 py-2.5 rounded-lg border focus:outline-none focus:ring-2 ${
                titleError
                  ? 'border-rose-400 focus:ring-rose-500/20'
                  : 'border-slate-300 focus:ring-medpark-500/20'
              }`}
            />
            {titleError && (
              <p role="alert" id="intake-title-error" className="text-[11px] font-semibold text-rose-700">
                {titleError}
              </p>
            )}
          </div>

          {/* Meeting Type & Workflow Mode Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Meeting Type */}
            <div className="space-y-1.5">
              <label htmlFor="intake-type" className="text-xs font-semibold text-slate-700">Meeting Type (Email Routing Policy)</label>
              <select
                id="intake-type"
                value={meetingType}
                onChange={(e) => setMeetingType(e.target.value as MeetingType)}
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              >
                <option value="medical">Medical Board (Clinical Council & Protocols)</option>
                <option value="executive">Executive Committee (Leadership & Governance)</option>
                <option value="administrative">Administrative & Hospital Operations</option>
              </select>
            </div>

            {/* Workflow Mode Switch */}
            <div className="space-y-1.5">
              <span className="block text-xs font-semibold text-slate-700" id="intake-mode-label">Pipeline Processing Mode</span>
              <div className="grid grid-cols-2 gap-2" role="group" aria-labelledby="intake-mode-label">
                <button
                  type="button"
                  onClick={() => setWorkflowMode('auto_pilot')}
                  aria-pressed={workflowMode === 'auto_pilot'}
                  className={`flex items-center justify-center space-x-1.5 p-2 rounded-lg border text-xs font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 ${
                    workflowMode === 'auto_pilot'
                      ? 'bg-blue-50 border-medpark-500 text-medpark-700 ring-1 ring-medpark-500'
                      : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <Rocket className="w-3.5 h-3.5 text-medpark-600" aria-hidden="true" />
                  <span>Auto-Pilot Processing</span>
                </button>

                <button
                  type="button"
                  onClick={() => setWorkflowMode('supervised')}
                  aria-pressed={workflowMode === 'supervised'}
                  className={`flex items-center justify-center space-x-1.5 p-2 rounded-lg border text-xs font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                    workflowMode === 'supervised'
                      ? 'bg-emerald-50 border-emerald-500 text-emerald-700 ring-1 ring-emerald-500'
                      : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <Shield className="w-3.5 h-3.5 text-emerald-600" aria-hidden="true" />
                  <span>Supervised (Clinical Gate)</span>
                </button>
              </div>

              {/* Both modes require human sign-off before email. */}
              {workflowMode === 'auto_pilot' ? (
                <p className="text-[11px] font-semibold text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2 flex items-start space-x-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 mt-px flex-shrink-0" aria-hidden="true" />
                  <span>Processing runs automatically. Minutes wait for your sign-off before any email is sent.</span>
                </p>
              ) : (
                <p className="text-[11px] text-slate-500">
                  Minutes wait for your sign-off before any email is sent.
                </p>
              )}
            </div>
          </div>

          {/* Agenda */}
          <div className="space-y-1.5">
            <label htmlFor="intake-agenda" className="text-xs font-semibold text-slate-700 flex items-center justify-between">
              <span>Agenda (Optional)</span>
              <span className="text-[11px] font-medium text-slate-500">Guides topic extraction</span>
            </label>
            <textarea
              id="intake-agenda"
              value={agenda}
              onChange={(e) => setAgenda(e.target.value)}
              rows={2}
              placeholder="e.g., 1. ICU sedation protocol  2. Cardiology case review  3. Q3 staffing"
              className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
          </div>

          {/* Audio Input: Mode-Specific */}
          <div className="space-y-2 p-4 rounded-xl bg-slate-50 border border-slate-200">
            {intakeMode === 'live' ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2 text-rose-800 text-xs font-bold">
                    <Radio className="w-4 h-4 text-rose-600 animate-pulse" />
                    <span>Live Conference Microphone</span>
                  </div>
                  <span className="text-[11px] text-slate-500 font-medium">Record in-person room dialogue</span>
                </div>
                <div className="p-3 bg-white rounded-xl border border-slate-200 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <AudioRecorder onAudioReady={(recordedFile) => handleSelectAudioFile(recordedFile)} />
                  <span className="text-[11px] text-slate-400 italic">
                    Press start when doctors begin speaking. Press stop when done.
                  </span>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="text-xs font-semibold text-slate-700 flex items-center justify-between">
                  <span>Audio File Selection</span>
                  <span id="intake-audio-hint" className="text-[11px] font-medium text-slate-500">
                    Supports WAV, MP3, M4A, WebM, OGG, FLAC
                  </span>
                </div>
                <label
                  htmlFor="intake-audio"
                  className="w-full flex flex-col items-center justify-center p-5 border-2 border-dashed border-slate-300 rounded-xl cursor-pointer hover:border-medpark-500 hover:bg-white transition-all text-xs text-slate-600 font-medium text-center space-y-1.5 focus-within:border-medpark-500 focus-within:ring-2 focus-within:ring-medpark-500/30"
                >
                  <UploadCloud className="w-6 h-6 text-slate-400" aria-hidden="true" />
                  <span className="font-semibold text-slate-800">
                    {audioFile ? audioFile.name : 'Click to select recorded audio file'}
                  </span>
                  <span className="text-[11px] text-slate-400">or drag and drop audio file here</span>
                  <input
                    id="intake-audio"
                    type="file"
                    accept="audio/*,.m4a,.webm,.ogg,.flac"
                    aria-describedby="intake-audio-hint"
                    onChange={(e) => {
                      if (e.target.files && e.target.files[0]) {
                        handleSelectAudioFile(e.target.files[0]);
                      }
                    }}
                    className="sr-only"
                  />
                </label>
              </div>
            )}

            {audioError && (
              <p role="alert" className="flex items-start space-x-1.5 text-xs text-rose-700 bg-rose-50 p-2 rounded-lg border border-rose-200">
                <AlertTriangle className="w-3.5 h-3.5 text-rose-600 flex-shrink-0 mt-px" aria-hidden="true" />
                <span className="leading-relaxed">{audioError}</span>
              </p>
            )}

            {audioFile && (
              <div className="flex items-center space-x-2 text-xs text-emerald-700 bg-emerald-50 p-2 rounded-lg border border-emerald-200">
                <FileAudio className="w-4 h-4 text-emerald-600 flex-shrink-0" aria-hidden="true" />
                <span className="truncate">
                  Ready for processing: {audioFile.name}{' '}
                  <span className="font-mono tabular-nums">({(audioFile.size / (1024 * 1024)).toFixed(2)} MB)</span>
                </span>
              </div>
            )}

            {!audioFile && (
              <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2.5">
                No recording attached. The meeting will be created empty — you can upload audio later.
              </p>
            )}
          </div>

          {/* Attendees Management */}
          <ParticipantSelector
            attendees={attendees}
            onChange={setAttendees}
            disabled={isSubmitting}
          />

          {/* Submit */}
          <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-100">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 font-medium rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              aria-busy={isSubmitting}
              className="inline-flex items-center space-x-2 px-5 py-2.5 bg-medpark-500 hover:bg-medpark-600 text-white font-semibold text-sm rounded-lg shadow-sm transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 focus-visible:ring-offset-2"
            >
              <Sparkles className="w-4 h-4" aria-hidden="true" />
              {/* The label states what will actually happen: no audio means no pipeline run */}
              <span>{audioFile ? 'Create & Start Pipeline' : 'Create Meeting (no audio yet)'}</span>
            </button>
          </div>
        </form>

      </div>
    </div>
  );
};
