import React, { useEffect, useState } from 'react';
import { ActionItem } from '../types';
import { useToast } from './Toast';
import {
  ListTodo,
  Play,
  Calendar,
  User,
  Search,
  Copy,
  CheckCircle2,
  Circle,
  AlertCircle,
  AlertTriangle,
  Filter,
} from 'lucide-react';

interface ActionItemsTableProps {
  actionItems: ActionItem[];
  onSeek: (startSec: number, endSec?: number) => void;
}

export const ActionItemsTable: React.FC<ActionItemsTableProps> = ({
  actionItems: initialActionItems,
  onSeek,
}) => {
  const { showToast } = useToast();
  const [items, setItems] = useState<ActionItem[]>(initialActionItems);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'open' | 'completed'>('all');
  const [priorityFilter, setPriorityFilter] = useState<string>('all');

  // Follow the minutes: a new meeting (or a new revision) must never keep the previous rows
  useEffect(() => {
    setItems(initialActionItems);
  }, [initialActionItems]);

  const toggleItemStatus = (id: string) => {
    setItems((prev) =>
      prev.map((item) => {
        if (item.id === id) {
          const nextStatus = item.status === 'completed' ? 'open' : 'completed';
          // Honest scope: the toggle is a local reading aid, it is not written back to the minutes
          showToast(
            nextStatus === 'completed' ? 'Marked complete (local view)' : 'Reopened (local view)',
            'Task state is not saved to the official minutes.',
            'info'
          );
          return { ...item, status: nextStatus };
        }
        return item;
      })
    );
  };

  const filteredItems = items.filter((item) => {
    if (statusFilter === 'open' && item.status === 'completed') return false;
    if (statusFilter === 'completed' && item.status !== 'completed') return false;
    if (priorityFilter !== 'all' && item.priority.toLowerCase() !== priorityFilter.toLowerCase()) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        item.task.toLowerCase().includes(q) ||
        item.owner.toLowerCase().includes(q) ||
        (item.deadline_phrase && item.deadline_phrase.toLowerCase().includes(q))
      );
    }
    return true;
  });

  const getPriorityBadge = (priority: string) => {
    switch (priority.toLowerCase()) {
      case 'high':
        return 'bg-rose-50 text-rose-700 border-rose-200';
      case 'medium':
        return 'bg-amber-50 text-amber-700 border-amber-200';
      case 'low':
        return 'bg-slate-100 text-slate-700 border-slate-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  // Same timecode notation as the transcript viewer so citations read identically everywhere
  const formatTimestamp = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const reviewedCount = items.filter((i) => i.is_reviewed).length;

  const clearFilters = () => {
    setStatusFilter('all');
    setPriorityFilter('all');
    setSearchQuery('');
  };

  const handleCopyActions = () => {
    if (filteredItems.length === 0) return;
    const text = filteredItems
      .map(
        (item, idx) =>
          `${idx + 1}. [${item.priority.toUpperCase()}] Owner: ${item.owner} | Task: ${
            item.task
          } | Deadline: ${item.deadline_date || item.deadline_phrase || 'Unspecified'} | Status: ${
            item.status
          }`
      )
      .join('\n');

    navigator.clipboard.writeText(text);
    showToast('Copied to clipboard', `${filteredItems.length} action items copied to clipboard.`);
  };

  return (
    <section
      aria-labelledby="action-items-heading"
      className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden"
    >
      {/* Header & Filter Bar */}
      <div className="p-4 bg-slate-50/80 border-b border-slate-200 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-lg bg-medpark-500 text-white flex items-center justify-center flex-shrink-0">
              <ListTodo className="w-4 h-4" />
            </div>
            <div>
              <h3 id="action-items-heading" className="font-bold text-slate-900 text-sm">
                Action Items &amp; Clinical Task Directives
              </h3>
              <p className="text-xs text-slate-500">Assigned task directives with clinical owners and deadlines</p>
              <p className="text-[11px] font-medium text-slate-500 tabular-nums mt-0.5">
                {reviewedCount} of {items.length} verified by a reviewer
              </p>
              <p className="text-[11px] text-slate-400 italic">Completion marks are local to this session.</p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <span
              role="status"
              className="text-xs font-semibold tabular-nums px-2.5 py-1 rounded-full bg-medpark-50 text-medpark-700 border border-medpark-500/25"
            >
              {filteredItems.length} tasks
            </span>
            <button
              onClick={handleCopyActions}
              disabled={filteredItems.length === 0}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-sm disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Copy action items list to clipboard"
            >
              <Copy className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
              <span>Copy</span>
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-col sm:flex-row items-center gap-2 pt-1">
          <div className="relative flex-1 w-full">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by task, owner, or deadline..."
              aria-label="Search action items"
              className="w-full text-xs pl-9 pr-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/40 focus:border-medpark-500"
            />
          </div>

          <div
            role="group"
            aria-label="Filter by status"
            className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200 w-full sm:w-auto"
          >
            {['all', 'open', 'completed'].map((st) => (
              <button
                key={st}
                onClick={() => setStatusFilter(st as any)}
                aria-pressed={statusFilter === st}
                className={`px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wide rounded transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 ${
                  statusFilter === st
                    ? 'bg-medpark-500 text-white'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {st}
              </button>
            ))}
          </div>

          <div
            role="group"
            aria-label="Filter by priority"
            className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200 w-full sm:w-auto"
          >
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600 ml-1.5 mr-1">Priority:</span>
            {['all', 'high', 'medium', 'low'].map((p) => (
              <button
                key={p}
                onClick={() => setPriorityFilter(p)}
                aria-pressed={priorityFilter === p}
                className={`px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wide rounded transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 ${
                  priorityFilter === p
                    ? 'bg-medpark-500 text-white'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Action Items List */}
      <div role="list" className="divide-y divide-slate-100">
        {filteredItems.map((item) => {
          const isCompleted = item.status === 'completed';
          const isGrounded = Boolean(item.evidence && item.evidence.length > 0);

          return (
            <div
              key={item.id}
              role="listitem"
              className={`p-4 space-y-2.5 transition-colors hover:bg-slate-50/60 border-l-4 ${
                isGrounded ? 'border-transparent' : 'border-amber-300'
              } ${isCompleted ? 'bg-slate-50/40 opacity-75' : ''}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start space-x-3 flex-1 min-w-0">
                  {/* Status Toggle Checkbox (local view only) */}
                  <button
                    onClick={() => toggleItemStatus(item.id)}
                    role="checkbox"
                    aria-checked={isCompleted}
                    aria-label={`Mark "${item.task}" as ${isCompleted ? 'open' : 'completed'}`}
                    className="mt-0.5 p-0.5 rounded-full text-slate-400 hover:text-medpark-600 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
                    title={isCompleted ? 'Mark as active' : 'Mark as completed'}
                  >
                    {isCompleted ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-600 fill-emerald-100" aria-hidden="true" />
                    ) : (
                      <Circle className="w-5 h-5 text-slate-300 hover:text-medpark-500" aria-hidden="true" />
                    )}
                  </button>

                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md border ${getPriorityBadge(
                          item.priority
                        )}`}
                      >
                        Priority: {item.priority}
                      </span>
                      <span className="text-xs font-bold text-slate-800 inline-flex items-center space-x-1 bg-slate-100 px-2 py-0.5 rounded-md border border-slate-200">
                        <User className="w-3 h-3 text-slate-500" aria-hidden="true" />
                        <span>{item.owner}</span>
                      </span>
                      {/* Read-only record of the per-item human verification */}
                      {item.is_reviewed ? (
                        <span className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-md">
                          <CheckCircle2 className="w-3 h-3" aria-hidden="true" />
                          <span>Verified</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-md">
                          <Circle className="w-3 h-3" aria-hidden="true" />
                          <span>Unverified</span>
                        </span>
                      )}
                    </div>

                    <p
                      className={`text-sm font-semibold text-slate-900 leading-snug break-words ${
                        isCompleted ? 'line-through text-slate-500' : ''
                      }`}
                    >
                      {item.task}
                    </p>
                  </div>
                </div>

                {/* Deadline tag */}
                <div className="flex flex-col items-end text-xs flex-shrink-0 max-w-[45%]">
                  <div className="flex items-center space-x-1 text-slate-700 font-mono font-bold tabular-nums bg-slate-100 px-2 py-1 rounded-md border border-slate-200">
                    <Calendar className="w-3.5 h-3.5 text-medpark-600 flex-shrink-0" aria-hidden="true" />
                    <span>{item.deadline_date || item.deadline_phrase || 'Unspecified'}</span>
                  </div>
                  {item.deadline_phrase && item.deadline_date && (
                    <span className="text-[10px] text-slate-600 italic mt-0.5 text-right break-words">
                      "{item.deadline_phrase}"
                    </span>
                  )}
                </div>
              </div>

              {/* Clickable Audio Evidence */}
              {isGrounded ? (
                <div className="flex flex-wrap gap-2 pt-0.5 pl-8">
                  {item.evidence.map((ev, idx) => (
                    <button
                      key={idx}
                      onClick={() => onSeek(ev.start, ev.end)}
                      aria-label={`Play audio evidence from ${Math.floor(ev.start)} to ${Math.floor(
                        ev.end
                      )} seconds: ${ev.quote}`}
                      className="group inline-flex items-center space-x-2 max-w-full text-xs text-medpark-700 bg-medpark-50 hover:bg-medpark-100 border border-medpark-500/25 hover:border-medpark-500/50 px-2.5 py-1.5 rounded-lg transition-colors motion-reduce:transition-none text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
                      title="Play this audio citation"
                    >
                      <span className="w-4 h-4 rounded-full bg-medpark-500 text-white flex items-center justify-center flex-shrink-0">
                        <Play className="w-2.5 h-2.5 fill-current" aria-hidden="true" />
                      </span>
                      <span className="font-mono font-bold text-[11px] tabular-nums flex-shrink-0">
                        {formatTimestamp(ev.start)} – {formatTimestamp(ev.end)}
                      </span>
                      <span className="italic truncate max-w-md text-slate-600">
                        "{ev.quote}"
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="pt-0.5 pl-8">
                  <span className="inline-flex items-center space-x-1.5 text-[11px] font-bold text-amber-800 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-lg">
                    <AlertTriangle className="w-3 h-3" aria-hidden="true" />
                    <span>No audio evidence — verify manually</span>
                  </span>
                </div>
              )}
            </div>
          );
        })}

        {filteredItems.length === 0 && (
          <div className="p-8 text-center space-y-3">
            <p className="text-sm text-slate-600">
              {items.length === 0
                ? 'No action items were extracted from this recording.'
                : 'No action items match your search filter.'}
            </p>
            {items.length > 0 && (
              <button
                onClick={clearFilters}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              >
                <Filter className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                <span>Clear filters</span>
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
};
