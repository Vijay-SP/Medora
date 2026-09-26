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
  Calendar,
  Users,
  Archive,
  FileCheck,
} from 'lucide-react';
import { Meeting } from '../types';
import { apiClient } from '../api/client';

interface MeetingVaultViewProps {
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
  pending_review: { label: 'Pending Review', badge: 'bg-amber-50 text-amber-800 border-amber-200 font-semibold' },
  approved: { label: 'Signed (Not Sent)', badge: 'bg-blue-50 text-blue-800 border-blue-200 font-semibold' },
  delivered: { label: 'Delivered', badge: 'bg-emerald-50 text-emerald-800 border-emerald-200 font-semibold' },
};

export const MeetingVaultView: React.FC<MeetingVaultViewProps> = ({
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

  const filteredMeetings = meetings.filter((m) => {
    if (workflowFilter !== 'all' && m.workflow_mode !== workflowFilter) return false;
    if (statusFilter !== 'all' && m.review_status !== statusFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchTitle = m.title.toLowerCase().includes(q);
      const matchType = m.meeting_type.toLowerCase().includes(q);
      const matchAttendees = m.attendees?.some((a: any) => {
        const name = typeof a === 'string' ? a : a?.name || '';
        const dept = typeof a === 'object' && a?.department ? a.department : '';
        return (
          (name && name.toLowerCase().includes(q)) ||
          (dept && dept.toLowerCase().includes(q))
        );
      });
      return matchTitle || matchType || matchAttendees;
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
      {/* Vault Header Bar */}
      <div className="bg-white rounded-3xl border border-slate-200 p-6 sm:p-7 shadow-xs">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-5">
          <div className="space-y-1.5 max-w-2xl">
            <div className="flex items-center space-x-2">
              <div className="w-9 h-9 rounded-xl bg-medpark-50 text-medpark-600 flex items-center justify-center flex-shrink-0">
                <Archive className="w-5 h-5" />
              </div>
              <h1 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight">
                Meeting Intelligence Vault
              </h1>
              <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200 tabular-nums">
                {totalCount} {totalCount === 1 ? 'session' : 'sessions'}
              </span>
            </div>
            <p className="text-xs sm:text-sm text-slate-500 leading-relaxed">
              Air-gapped repository of clinical session recordings, neural transcripts, multi-language minutes, and signed document revisions.
            </p>
          </div>

          {/* Quick Intake Shortcuts */}
          <div className="flex items-center space-x-2.5 flex-shrink-0">
            <button
              onClick={onUploadRecording}
              className="inline-flex items-center space-x-2 px-3.5 py-2.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-bold text-slate-700 shadow-xs transition-colors"
            >
              <UploadCloud className="w-4 h-4 text-blue-600" />
              <span>Upload Audio</span>
            </button>
            <button
              onClick={onStartLiveMeeting}
              className="inline-flex items-center space-x-2 px-4 py-2.5 rounded-xl bg-rose-600 hover:bg-rose-700 text-xs font-bold text-white shadow-xs transition-colors"
            >
              <Mic className="w-4 h-4" />
              <span>Start Live Session</span>
            </button>
          </div>
        </div>

        {/* Search & Filter Bar */}
        <div className="mt-6 pt-5 border-t border-slate-100 flex flex-col md:flex-row md:items-center justify-between gap-3">
          {/* Search box */}
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search sessions by title, type, or attendee..."
              className="w-full text-xs pl-9 pr-8 py-2 rounded-xl border border-slate-300 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
            {searchQuery && (
              <button
                onClick={() => onSearchChange('')}
                className="absolute right-2.5 top-2 p-0.5 text-slate-400 hover:text-slate-700"
                title="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={workflowFilter}
              onChange={(e) => onWorkflowFilterChange(e.target.value)}
              className="text-xs font-semibold px-3 py-2 rounded-xl border border-slate-300 bg-slate-50 text-slate-700 focus:outline-none"
            >
              <option value="all">All Workflow Modes</option>
              <option value="supervised">Supervised (Clinical Gate)</option>
              <option value="auto_pilot">Auto-Pilot</option>
            </select>

            <select
              value={statusFilter}
              onChange={(e) => onStatusFilterChange(e.target.value)}
              className="text-xs font-semibold px-3 py-2 rounded-xl border border-slate-300 bg-slate-50 text-slate-700 focus:outline-none"
            >
              <option value="all">All Review Statuses</option>
              <option value="pending_review">Pending Review</option>
              <option value="approved">Signed (Not Sent)</option>
              <option value="delivered">Delivered</option>
              <option value="draft">Draft</option>
            </select>

            {hasFilters && (
              <button
                onClick={onClearFilters}
                className="px-3 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors"
              >
                Reset Filters
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Vault Meetings List */}
      <div className="bg-white rounded-3xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="px-6 py-4 bg-slate-50/70 border-b border-slate-200 flex items-center justify-between">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-600">
            {hasFilters ? `Filtered Sessions (${filteredMeetings.length} of ${totalCount})` : `All Sessions (${totalCount})`}
          </span>
          <span className="text-[11px] text-slate-400 font-medium">
            Sorted by scheduled date (newest first)
          </span>
        </div>

        <div className="divide-y divide-slate-100">
          {filteredMeetings.length === 0 ? (
            <div className="p-16 text-center space-y-3.5">
              <div className="w-14 h-14 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
                <Archive className="w-7 h-7" />
              </div>
              <h3 className="text-sm font-bold text-slate-800">
                {totalCount === 0 ? 'Your Intelligence Vault is empty' : 'No sessions match your search or filter'}
              </h3>
              <p className="text-xs text-slate-500 max-w-sm mx-auto">
                {totalCount === 0
                  ? 'Start by recording live conference room audio or uploading audio files.'
                  : 'Try resetting your filter parameters or searching for a different keyword.'}
              </p>
              {totalCount === 0 ? (
                <div className="pt-2 flex justify-center space-x-2">
                  <button
                    onClick={onStartLiveMeeting}
                    className="inline-flex items-center space-x-1.5 px-4 py-2 bg-rose-600 text-white rounded-xl text-xs font-bold hover:bg-rose-700 shadow-xs"
                  >
                    <Mic className="w-3.5 h-3.5" />
                    <span>Start Live Session</span>
                  </button>
                  <button
                    onClick={onUploadRecording}
                    className="inline-flex items-center space-x-1.5 px-4 py-2 bg-slate-800 text-white rounded-xl text-xs font-bold hover:bg-slate-900 shadow-xs"
                  >
                    <UploadCloud className="w-3.5 h-3.5" />
                    <span>Upload Recording</span>
                  </button>
                </div>
              ) : (
                <button
                  onClick={onClearFilters}
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-bold transition-colors"
                >
                  <span>Reset all filters</span>
                </button>
              )}
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
                  className={`p-5 sm:p-6 flex flex-col md:flex-row md:items-center justify-between gap-4 transition-colors ${
                    isSelected ? 'bg-medpark-50/40' : 'hover:bg-slate-50/70'
                  }`}
                >
                  {/* Left: Meeting Info */}
                  <div className="min-w-0 space-y-1.5 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        onClick={() => onOpenWorkspace(meeting.id)}
                        className="font-bold text-sm sm:text-base text-slate-900 hover:text-medpark-600 cursor-pointer transition-colors"
                      >
                        {meeting.title}
                      </span>
                      <span className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full border ${statusMeta.badge}`}>
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
                      {meeting.current_revision > 1 && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                          Rev. {meeting.current_revision}
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
                          <span className="flex items-center space-x-1">
                            <Clock className="w-3.5 h-3.5 text-slate-400" />
                            <span className="font-mono text-[11px]">
                              {formatDuration(meeting.audio_duration_seconds)}
                            </span>
                          </span>
                        </>
                      )}

                      <span>•</span>

                      <span className="capitalize text-[11px] font-semibold text-slate-600 bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                        {meeting.meeting_type.replace('_', ' ')}
                      </span>
                    </div>

                    {/* Attendees quick preview */}
                    {meeting.attendees && meeting.attendees.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {meeting.attendees.slice(0, 4).map((att, idx) => {
                          const name = typeof att === 'string' ? att : att.name;
                          const dept = typeof att === 'object' && att.department ? ` (${att.department})` : '';
                          return (
                            <span
                              key={idx}
                              className="text-[11px] font-medium bg-slate-100 text-slate-700 px-2 py-0.5 rounded-md border border-slate-200"
                            >
                              {name}{dept}
                            </span>
                          );
                        })}
                        {meeting.attendees.length > 4 && (
                          <span className="text-[11px] font-semibold text-slate-400 self-center">
                            +{meeting.attendees.length - 4} more
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Right: Actions */}
                  <div className="flex items-center space-x-2 flex-shrink-0 self-start md:self-auto">
                    <button
                      onClick={() => onOpenWorkspace(meeting.id)}
                      className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-xl bg-medpark-500 hover:bg-medpark-600 text-white font-bold text-xs shadow-xs transition-colors"
                      title="Open in Workspace"
                    >
                      <FileSpreadsheet className="w-3.5 h-3.5" />
                      <span>Workspace</span>
                      <ChevronRight className="w-3.5 h-3.5 ml-0.5" />
                    </button>

                    {/* Download PDF */}
                    <a
                      href={apiClient.getPdfDownloadUrl(meeting.id)}
                      download
                      title="Download Official PDF Minutes"
                      className="p-2 text-slate-600 hover:text-medpark-600 hover:bg-slate-100 rounded-xl border border-slate-200 transition-colors"
                    >
                      <FileDown className="w-4 h-4" />
                    </a>

                    {/* Download DOCX */}
                    <a
                      href={apiClient.getDocxDownloadUrl(meeting.id)}
                      download
                      title="Download Official DOCX Minutes"
                      className="p-2 text-slate-600 hover:text-blue-600 hover:bg-slate-100 rounded-xl border border-slate-200 transition-colors"
                    >
                      <FileText className="w-4 h-4" />
                    </a>

                    {/* Delete */}
                    <button
                      onClick={() => onDeleteMeeting(meeting)}
                      title="Delete Session Record"
                      className="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-xl border border-slate-200 transition-colors"
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
