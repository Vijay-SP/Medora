import React from 'react';
import {
  FileText,
  Clock,
  CheckCircle2,
  AlertCircle,
  Search,
  Filter,
  X,
  Plus,
  Mic,
  UploadCloud,
  FileSpreadsheet,
  FileDown,
  Trash2,
  Layers,
  ChevronRight,
  ShieldCheck,
  Radio,
  Calendar,
  Users,
} from 'lucide-react';
import { Meeting } from '../types';
import { apiClient } from '../api/client';

interface DashboardViewProps {
  meetings: Meeting[];
  selectedMeetingId: string | null;
  onSelectMeeting: (id: string) => void;
  onOpenWorkspace: (id: string) => void;
  onStartLiveMeeting: () => void;
  onUploadRecording: () => void;
  onDeleteMeeting: (meeting: Meeting) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  workflowFilter: string;
  onWorkflowFilterChange: (w: string) => void;
  statusFilter: string;
  onStatusFilterChange: (s: string) => void;
  onClearFilters: () => void;
}

const REVIEW_STATUS_META: Record<string, { label: string; badge: string }> = {
  draft: { label: 'Draft', badge: 'bg-slate-100 text-slate-700 border-slate-200' },
  pending_review: { label: 'Pending Review', badge: 'bg-amber-50 text-amber-800 border-amber-200' },
  approved: { label: 'Signed (Not Sent)', badge: 'bg-blue-50 text-blue-800 border-blue-200' },
  delivered: { label: 'Delivered', badge: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
};

export const DashboardView: React.FC<DashboardViewProps> = ({
  meetings,
  selectedMeetingId,
  onSelectMeeting,
  onOpenWorkspace,
  onStartLiveMeeting,
  onUploadRecording,
  onDeleteMeeting,
  searchQuery,
  onSearchChange,
  workflowFilter,
  onWorkflowFilterChange,
  statusFilter,
  onStatusFilterChange,
  onClearFilters,
}) => {
  const totalCount = meetings.length;
  const pendingCount = meetings.filter(
    (m) => m.review_status === 'pending_review' || m.review_status === 'draft' || m.review_status === 'approved'
  ).length;
  const deliveredCount = meetings.filter((m) => m.review_status === 'delivered').length;

  const filteredMeetings = meetings.filter((m) => {
    if (workflowFilter !== 'all' && m.workflow_mode !== workflowFilter) return false;
    if (statusFilter !== 'all' && m.review_status !== statusFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return m.title.toLowerCase().includes(q) || m.meeting_type.toLowerCase().includes(q);
    }
    return true;
  });

  const hasFilters = workflowFilter !== 'all' || statusFilter !== 'all' || searchQuery.trim() !== '';

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
    <div className="space-y-6">
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

        {/* Two Big Primary Action Cards */}
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
        {/* Total Meetings */}
        <div className="p-4 bg-white rounded-2xl border border-slate-200 shadow-xs flex items-center space-x-4">
          <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center flex-shrink-0">
            <FileText className="w-6 h-6" />
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Total Recorded Sessions</p>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-black text-slate-900 tabular-nums">{totalCount}</span>
              <span className="text-xs text-slate-500 font-medium">meetings in vault</span>
            </div>
          </div>
        </div>

        {/* Pending Review */}
        <div className="p-4 bg-white rounded-2xl border border-slate-200 shadow-xs flex items-center space-x-4">
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
        <div className="p-4 bg-white rounded-2xl border border-slate-200 shadow-xs flex items-center space-x-4">
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

      {/* Meeting Management & Filter Bar */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-5 border-b border-slate-200 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-bold text-slate-900">Meeting Intelligence Vault</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Browse, filter, and open sessions directly into the dedicated workspace.
            </p>
          </div>

          {/* Search & Filter Controls */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px]">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Search sessions..."
                className="w-full text-xs pl-8 pr-8 py-2 rounded-xl border border-slate-300 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              />
              {searchQuery && (
                <button
                  onClick={() => onSearchChange('')}
                  className="absolute right-2 top-2 p-0.5 text-slate-400 hover:text-slate-700"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            <select
              value={workflowFilter}
              onChange={(e) => onWorkflowFilterChange(e.target.value)}
              className="text-xs font-semibold px-3 py-2 rounded-xl border border-slate-300 bg-slate-50 text-slate-700 focus:outline-none"
            >
              <option value="all">All Modes</option>
              <option value="supervised">Supervised</option>
              <option value="auto_pilot">Auto-Pilot</option>
            </select>

            <select
              value={statusFilter}
              onChange={(e) => onStatusFilterChange(e.target.value)}
              className="text-xs font-semibold px-3 py-2 rounded-xl border border-slate-300 bg-slate-50 text-slate-700 focus:outline-none"
            >
              <option value="all">All Statuses</option>
              <option value="pending_review">Pending Review</option>
              <option value="approved">Approved</option>
              <option value="delivered">Delivered</option>
              <option value="draft">Draft</option>
            </select>

            {hasFilters && (
              <button
                onClick={onClearFilters}
                className="px-2.5 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors"
              >
                Reset
              </button>
            )}
          </div>
        </div>

        {/* Meetings List / Table */}
        <div className="divide-y divide-slate-100">
          {filteredMeetings.length === 0 ? (
            <div className="p-12 text-center space-y-3">
              <FileSpreadsheet className="w-12 h-12 text-slate-300 mx-auto" />
              <p className="text-sm font-semibold text-slate-700">No meetings found</p>
              <p className="text-xs text-slate-400 max-w-sm mx-auto">
                {totalCount === 0
                  ? 'Get started by launching a live meeting or uploading a pre-recorded audio file above.'
                  : 'No meetings matched your current filters. Try resetting the search or filter options.'}
              </p>
            </div>
          ) : (
            filteredMeetings.map((meeting) => {
              const statusMeta = REVIEW_STATUS_META[meeting.review_status] || {
                label: meeting.review_status,
                badge: 'bg-slate-100 text-slate-700 border-slate-200',
              };
              const isSelected = selectedMeetingId === meeting.id;

              return (
                <div
                  key={meeting.id}
                  className={`p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-colors ${
                    isSelected ? 'bg-medpark-50/50' : 'hover:bg-slate-50'
                  }`}
                >
                  {/* Left: Meeting Info */}
                  <div className="min-w-0 space-y-1 flex-1">
                    <div className="flex items-center space-x-2.5">
                      <span className="font-bold text-sm text-slate-900 hover:text-medpark-600 cursor-pointer" onClick={() => onOpenWorkspace(meeting.id)}>
                        {meeting.title}
                      </span>
                      <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${statusMeta.badge}`}>
                        {statusMeta.label}
                      </span>
                      {meeting.workflow_mode === 'auto_pilot' && (
                        <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200">
                          Auto-Pilot
                        </span>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
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

                      <span className="capitalize text-[11px] font-medium text-slate-400">
                        [{meeting.meeting_type}]
                      </span>
                    </div>
                  </div>

                  {/* Right: Actions */}
                  <div className="flex items-center space-x-2 flex-shrink-0">
                    <button
                      onClick={() => onOpenWorkspace(meeting.id)}
                      className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-xl bg-medpark-500 hover:bg-medpark-600 text-white font-bold text-xs shadow-xs transition-colors"
                    >
                      <FileSpreadsheet className="w-3.5 h-3.5" />
                      <span>Workspace</span>
                      <ChevronRight className="w-3.5 h-3.5 ml-0.5" />
                    </button>

                    {/* Download Exports */}
                    <a
                      href={apiClient.getPdfDownloadUrl(meeting.id)}
                      download
                      title="Download PDF Minutes"
                      className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors"
                    >
                      <FileDown className="w-4 h-4" />
                    </a>

                    {/* Delete */}
                    <button
                      onClick={() => onDeleteMeeting(meeting)}
                      title="Delete Meeting Record"
                      className="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg border border-slate-200 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
