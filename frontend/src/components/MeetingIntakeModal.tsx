import React, { useState } from 'react';
import { MeetingCreate, MeetingType, WorkflowMode, Attendee } from '../types';
import { AudioRecorder } from './AudioRecorder';
import { UploadCloud, FileAudio, Users, Sparkles, X, Plus, Trash2, Rocket, Shield } from 'lucide-react';

interface MeetingIntakeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (meetingData: MeetingCreate, audioFile?: File) => Promise<void>;
}

export const MeetingIntakeModal: React.FC<MeetingIntakeModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
}) => {
  const [title, setTitle] = useState('');
  const [meetingType, setMeetingType] = useState<MeetingType>('medical');
  const [workflowMode, setWorkflowMode] = useState<WorkflowMode>('supervised');
  const [agenda, setAgenda] = useState('');
  const [audioFile, setAudioFile] = useState<File | null>(null);
  
  // Default Medpark attendees
  const [attendees, setAttendees] = useState<Attendee[]>([
    { id: '1', name: 'Dr. Elena Ceban', role: 'Medical Director / Surgeon', email: 'elena.ceban@medpark.md' },
    { id: '2', name: 'Dr. Mihail Popov', role: 'Chief of Intensive Care (ICU)', email: 'mihail.popov@medpark.md' },
  ]);

  const [newAttendeeName, setNewAttendeeName] = useState('');
  const [newAttendeeEmail, setNewAttendeeEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleAddAttendee = () => {
    if (!newAttendeeName.trim() || !newAttendeeEmail.trim()) return;
    setAttendees([
      ...attendees,
      {
        id: Date.now().toString(),
        name: newAttendeeName.trim(),
        role: 'Participant',
        email: newAttendeeEmail.trim(),
      },
    ]);
    setNewAttendeeName('');
    setNewAttendeeEmail('');
  };

  const handleRemoveAttendee = (id: string) => {
    setAttendees(attendees.filter((a) => a.id !== id));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;

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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-2xl overflow-hidden my-8 animate-in fade-in zoom-in-95 duration-150">
        
        {/* Header */}
        <div className="p-5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div>
            <h3 className="font-bold text-slate-900 text-base">Configure New Meeting Intake</h3>
            <p className="text-xs text-slate-500">100% offline automated minutes for Medpark</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Title */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700">Meeting Title</label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g., Medical Board - ICU Protocols & Cardiology Cases"
              className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
          </div>

          {/* Meeting Type & Workflow Mode Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Meeting Type */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-700">Meeting Type (Email Routing Policy)</label>
              <select
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
              <label className="text-xs font-semibold text-slate-700">Pipeline Processing Mode</label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setWorkflowMode('auto_pilot')}
                  className={`flex items-center justify-center space-x-1.5 p-2 rounded-lg border text-xs font-medium transition-all ${
                    workflowMode === 'auto_pilot'
                      ? 'bg-blue-50 border-medpark-500 text-medpark-700 ring-1 ring-medpark-500'
                      : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <Rocket className="w-3.5 h-3.5 text-medpark-600" />
                  <span>Auto-Pilot (Zero-Click)</span>
                </button>

                <button
                  type="button"
                  onClick={() => setWorkflowMode('supervised')}
                  className={`flex items-center justify-center space-x-1.5 p-2 rounded-lg border text-xs font-medium transition-all ${
                    workflowMode === 'supervised'
                      ? 'bg-emerald-50 border-emerald-500 text-emerald-700 ring-1 ring-emerald-500'
                      : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <Shield className="w-3.5 h-3.5 text-emerald-600" />
                  <span>Supervised (Clinical Gate)</span>
                </button>
              </div>
            </div>
          </div>

          {/* Audio Input: Upload or Mic */}
          <div className="space-y-2 p-4 rounded-xl bg-slate-50 border border-slate-200">
            <label className="text-xs font-semibold text-slate-700 flex items-center justify-between">
              <span>Audio Recording (WAV, MP3, M4A, WebM)</span>
              <span className="text-[11px] text-slate-500">Upload audio file or record via microphone</span>
            </label>

            <div className="flex flex-col sm:flex-row items-center gap-3">
              {/* File upload input */}
              <label className="flex-1 w-full flex items-center justify-center space-x-2 px-4 py-2.5 border-2 border-dashed border-slate-300 rounded-lg cursor-pointer hover:border-medpark-500 hover:bg-white transition-all text-xs text-slate-600 font-medium">
                <UploadCloud className="w-4 h-4 text-slate-400" />
                <span>{audioFile ? audioFile.name : 'Select audio file'}</span>
                <input
                  type="file"
                  accept="audio/*,.m4a,.webm"
                  onChange={(e) => {
                    if (e.target.files && e.target.files[0]) {
                      setAudioFile(e.target.files[0]);
                    }
                  }}
                  className="hidden"
                />
              </label>

              <span className="text-xs font-semibold text-slate-400">or</span>

              {/* In-browser Mic recorder */}
              <AudioRecorder onAudioReady={(recordedFile) => setAudioFile(recordedFile)} />
            </div>

            {audioFile && (
              <div className="flex items-center space-x-2 text-xs text-emerald-700 bg-emerald-50 p-2 rounded border border-emerald-200">
                <FileAudio className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                <span className="truncate">Ready for processing: {audioFile.name} ({(audioFile.size / (1024 * 1024)).toFixed(2)} MB)</span>
              </div>
            )}
          </div>

          {/* Attendees Management */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-700 flex items-center space-x-1.5">
              <Users className="w-3.5 h-3.5 text-slate-500" />
              <span>Registered Participants ({attendees.length})</span>
            </label>

            <div className="max-h-36 overflow-y-auto divide-y divide-slate-100 rounded-lg border border-slate-200 p-2 space-y-1">
              {attendees.map((att) => (
                <div key={att.id} className="flex items-center justify-between text-xs py-1 px-1.5 hover:bg-slate-50 rounded">
                  <div>
                    <span className="font-semibold text-slate-800">{att.name}</span>
                    <span className="text-slate-500 ml-2">({att.email})</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRemoveAttendee(att.id)}
                    className="text-slate-400 hover:text-rose-600 p-1"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>

            {/* Quick add attendee */}
            <div className="flex items-center space-x-2 pt-1">
              <input
                type="text"
                value={newAttendeeName}
                onChange={(e) => setNewAttendeeName(e.target.value)}
                placeholder="Participant name"
                className="flex-1 text-xs px-2.5 py-1.5 rounded border border-slate-300"
              />
              <input
                type="email"
                value={newAttendeeEmail}
                onChange={(e) => setNewAttendeeEmail(e.target.value)}
                placeholder="email@medpark.md"
                className="flex-1 text-xs px-2.5 py-1.5 rounded border border-slate-300"
              />
              <button
                type="button"
                onClick={handleAddAttendee}
                className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Submit */}
          <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-100">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 font-medium rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center space-x-2 px-5 py-2.5 bg-medpark-500 hover:bg-medpark-600 text-white font-semibold text-sm rounded-lg shadow-sm disabled:opacity-50"
            >
              <Sparkles className="w-4 h-4" />
              <span>Create & Start Pipeline</span>
            </button>
          </div>
        </form>

      </div>
    </div>
  );
};
