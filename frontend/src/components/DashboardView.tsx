import React from 'react';
import {
  FileText,
  Clock,
  CheckCircle2,
  AlertCircle,
  Plus,
  Mic,
  UploadCloud,
  FileSpreadsheet,
  ChevronRight,
  ShieldCheck,
  Calendar,
  Users,
  Archive,
  ArrowRight,
  Cpu,
  Lock,
  Sparkles,
} from 'lucide-react';
import { Meeting } from '../types';

interface DashboardViewProps {
  meetings: Meeting[];
  selectedMeetingId: string | null;
  onSelectMeeting: (id: string) => void;
  onOpenWorkspace: (id: string) => void;
  onOpenVault: () => void;
  onStartLiveMeeting: () => void;
  onUploadRecording: () => void;
  onOpenDeliveries?: () => void;
}

const REVIEW_STATUS_META: Record<string, { label: string; badge: string }> = {
  draft: { label: 'Draft', badge: 'bg-slate-100 text-slate-700 border-slate-200' },
  pending_review: { label: 'Pending Review', badge: 'bg-amber-50 text-amber-800 border-amber-200 font-semibold' },
  approved: { label: 'Signed (Not Sent)', badge: 'bg-blue-50 text-blue-800 border-blue-200 font-semibold' },
  delivered: { label: 'Delivered', badge: 'bg-emerald-50 text-emerald-800 border-emerald-200 font-semibold' },
};

export const DashboardView: React.FC<DashboardViewProps> = ({
  meetings,
  selectedMeetingId,
  onSelectMeeting,
  onOpenWorkspace,
  onOpenVault,
  onStartLiveMeeting,
  onUploadRecording,
  onOpenDeliveries,
}) => {
  const totalCount = meetings.length;
  const pendingCount = meetings.filter(
    (m) => m.review_status === 'pending_review' || m.review_status === 'draft' || m.review_status === 'approved'
  ).length;
  const deliveredCount = meetings.filter((m) => m.review_status === 'delivered').length;

  // Recent 4 meetings for the executive preview
  const recentMeetings = [...meetings]
    .sort((a, b) => new Date(b.scheduled_at).getTime() - new Date(a.scheduled_at).getTime())
    .slice(0, 4);

  const formatMeetingDate = (iso: string) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'No date';
    return d.toLocaleDateString(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatDuration = (secs?: number) => {
    if (!secs || secs <= 0) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}m ${s}s`;
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Top Welcome & Quick Action Hero */}
      <div className="bg-gradient-to-r from-slate-900 via-medpark-900 to-slate-900 text-white p-6 sm:p-8 rounded-3xl shadow-sm relative overflow-hidden">
        <div className="relative z-10 max-w-2xl space-y-2">
          <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-white/10 backdrop-blur-sm border border-white/10 text-xs font-semibold text-emerald-300">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Air-Gapped Offline Hospital Architecture</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-black tracking-tight">
            Clinical Meeting Intelligence
          </h1>
          <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
            Medora transforms Romanian, Russian, and multilingual medical board dialogues into structured, evidence-grounded decisions and signed minutes.
          </p>
        </div>

        {/* Two Primary Action Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6 relative z-10">
          {/* Card 1: Start Live Meeting */}
          <button
            onClick={onStartLiveMeeting}
            className="flex items-start space-x-4 p-4 rounded-2xl bg-white/10 hover:bg-white/15 border border-white/15 text-left transition-all group backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-rose-400"
          >
            <div className="w-12 h-12 rounded-xl bg-rose-500/20 text-rose-400 border border-rose-500/30 flex items-center justify-center flex-shrink-0 group-hover:scale-105 transition-transform">
              <Mic className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-bold text-sm text-white">Start Live Meeting</span>
                <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-rose-500 text-white">
                  Live Mic
                </span>
              </div>
              <p className="text-xs text-slate-300 mt-1 leading-snug">
                Record in-person conference room audio directly from your microphone with real-time level feedback.
              </p>
            </div>
          </button>

          {/* Card 2: Upload Recording */}
          <button
            onClick={onUploadRecording}
            className="flex items-start space-x-4 p-4 rounded-2xl bg-white/10 hover:bg-white/15 border border-white/15 text-left transition-all group backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            <div className="w-12 h-12 rounded-xl bg-blue-500/20 text-blue-400 border border-blue-500/30 flex items-center justify-center flex-shrink-0 group-hover:scale-105 transition-transform">
              <UploadCloud className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-bold text-sm text-white">Upload Audio Recording</span>
                <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-blue-500 text-white">
                  File Intake
                </span>
              </div>
              <p className="text-xs text-slate-300 mt-1 leading-snug">
                Upload existing recorded audio files (.wav, .mp3, .m4a) for asynchronous offline processing.
              </p>
            </div>
          </button>
        </div>
      </div>

      {/* KPI Stats Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Total Meetings -> Links to Vault */}
        <div
          onClick={onOpenVault}
          className="p-5 bg-white hover:bg-slate-50/80 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between cursor-pointer group transition-all"
        >
          <div className="flex items-center space-x-4">
            <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center flex-shrink-0 group-hover:scale-105 transition-transform">
              <Archive className="w-6 h-6" />
            </div>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Meeting Intelligence Vault</p>
              <div className="flex items-baseline space-x-2">
                <span className="text-2xl font-black text-slate-900 tabular-nums">{totalCount}</span>
                <span className="text-xs text-slate-500 font-medium">sessions stored</span>
              </div>
            </div>
          </div>
          <div className="text-slate-300 group-hover:text-medpark-600 transition-colors">
            <ChevronRight className="w-5 h-5" />
          </div>
        </div>

        {/* Pending Review */}
        <div className="p-5 bg-white rounded-2xl border border-slate-200 shadow-xs flex items-center space-x-4">
          <div className="w-12 h-12 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center flex-shrink-0">
            <Clock className="w-6 h-6" />
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-amber-700">Pending Clinical Gate</p>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-black text-amber-900 tabular-nums">{pendingCount}</span>
              <span className="text-xs text-amber-600 font-medium">awaiting sign-off</span>
            </div>
          </div>
        </div>

        {/* Delivered Dispatches */}
        <div
          onClick={onOpenDeliveries}
          className={`p-5 bg-white rounded-2xl border border-slate-200 shadow-xs flex items-center space-x-4 ${
            onOpenDeliveries ? 'cursor-pointer hover:bg-slate-50/80 transition-colors' : ''
          }`}
        >
          <div className="w-12 h-12 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center flex-shrink-0">
            <CheckCircle2 className="w-6 h-6" />
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">Delivered Minutes</p>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-black text-emerald-900 tabular-nums">{deliveredCount}</span>
              <span className="text-xs text-emerald-600 font-medium">dispatched via SMTP</span>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Sessions Preview Card */}
      <div className="bg-white rounded-3xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-5 sm:p-6 border-b border-slate-100 flex items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-medpark-50 text-medpark-600 flex items-center justify-center flex-shrink-0">
              <FileSpreadsheet className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900">Recent Sessions</h2>
              <p className="text-xs text-slate-500">Quick access to recently recorded medical council dialogues</p>
            </div>
          </div>

          <button
            onClick={onOpenVault}
            className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-medpark-700 bg-medpark-50 hover:bg-medpark-100 border border-medpark-200 transition-colors"
          >
            <span>View All in Vault ({totalCount})</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {recentMeetings.length === 0 ? (
          <div className="p-10 text-center space-y-3">
            <Archive className="w-10 h-10 text-slate-300 mx-auto" />
            <p className="text-sm font-semibold text-slate-700">No sessions recorded yet</p>
            <p className="text-xs text-slate-400 max-w-sm mx-auto">
              Start by launching a live session with your room microphone or uploading an audio file.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {recentMeetings.map((meeting) => {
              const statusMeta = REVIEW_STATUS_META[meeting.review_status] || {
                label: meeting.review_status,
                badge: 'bg-slate-100 text-slate-700 border-slate-200',
              };

              return (
                <div
                  key={meeting.id}
                  className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-slate-50/70 transition-colors"
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        onClick={() => onOpenWorkspace(meeting.id)}
                        className="font-bold text-sm text-slate-900 hover:text-medpark-600 cursor-pointer transition-colors"
                      >
                        {meeting.title}
                      </span>
                      <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${statusMeta.badge}`}>
                        {statusMeta.label}
                      </span>
                      {meeting.workflow_mode === 'auto_pilot' ? (
                        <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200">
                          Auto-Pilot
                        </span>
                      ) : (
                        <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-50 text-slate-600 border border-slate-200">
                          Supervised
                        </span>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-2.5 text-xs text-slate-500">
                      <span className="flex items-center space-x-1">
                        <Calendar className="w-3.5 h-3.5 text-slate-400" />
                        <span>{formatMeetingDate(meeting.scheduled_at)}</span>
                      </span>

                      <span>•</span>

                      <span className="flex items-center space-x-1">
                        <Users className="w-3.5 h-3.5 text-slate-400" />
                        <span>{meeting.attendees?.length || 0} participants</span>
                      </span>

                      {meeting.audio_duration_seconds > 0 && (
                        <>
                          <span>•</span>
                          <span className="font-mono text-[11px]">
                            {formatDuration(meeting.audio_duration_seconds)}
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  <button
                    onClick={() => onOpenWorkspace(meeting.id)}
                    className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-white hover:bg-slate-100 border border-slate-200 text-slate-700 font-bold text-xs transition-colors self-start sm:self-auto shadow-xs"
                  >
                    <span>Open Workspace</span>
                    <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Hospital Air-Gap & Security Guarantee Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
        <div className="p-4 bg-white rounded-2xl border border-slate-200 shadow-xs space-y-1.5">
          <div className="flex items-center space-x-2 text-medpark-600">
            <Lock className="w-4 h-4" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900">Zero Cloud Egress</h3>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            All neural models run locally on hospital premises. Recordings and clinical data never leave the facility.
          </p>
        </div>

        <div className="p-4 bg-white rounded-2xl border border-slate-200 shadow-xs space-y-1.5">
          <div className="flex items-center space-x-2 text-blue-600">
            <Sparkles className="w-4 h-4" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900">Trilingual Synthesis</h3>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            Native multi-language extraction supporting Romanian, Russian, and English with audio-grounded timestamps.
          </p>
        </div>

        <div className="p-4 bg-white rounded-2xl border border-slate-200 shadow-xs space-y-1.5">
          <div className="flex items-center space-x-2 text-emerald-600">
            <CheckCircle2 className="w-4 h-4" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900">Clinical Review Gate</h3>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            Supervised workflow requires human clinician sign-off on summaries and actions before any email dispatch.
          </p>
        </div>
      </div>
    </div>
  );
};
