import React, { useState } from 'react';
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

  const toggleItemStatus = (id: string) => {
    setItems((prev) =>
      prev.map((item) => {
        if (item.id === id) {
          const nextStatus = item.status === 'completed' ? 'open' : 'completed';
          showToast(
            nextStatus === 'completed' ? 'Task completed' : 'Task reactivated',
            `"${item.task}" marked as ${nextStatus}.`
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
    <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
      {/* Header & Filter Bar */}
      <div className="p-4 bg-slate-50/80 border-b border-slate-200 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-lg bg-medpark-500 text-white flex items-center justify-center">
              <ListTodo className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 text-sm">Action Items & Clinical Task Directives</h3>
              <p className="text-xs text-slate-500">Assigned task directives with clinical owners and deadlines</p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-medpark-50 text-medpark-700 border border-medpark-200">
              {filteredItems.length} tasks
            </span>
            <button
              onClick={handleCopyActions}
              disabled={filteredItems.length === 0}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-2xs disabled:opacity-50"
              title="Copy action items list to clipboard"
            >
              <Copy className="w-3.5 h-3.5 text-slate-500" />
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
              className="w-full text-xs pl-9 pr-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
          </div>

          <div className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200 w-full sm:w-auto">
            {['all', 'open', 'completed'].map((st) => (
              <button
                key={st}
                onClick={() => setStatusFilter(st as any)}
                className={`px-2.5 py-1 text-[11px] font-bold uppercase rounded transition-colors ${
                  statusFilter === st
                    ? 'bg-medpark-500 text-white shadow-2xs'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {st}
              </button>
            ))}
          </div>

          <div className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200 w-full sm:w-auto">
            <span className="text-[10px] font-bold uppercase text-slate-400 ml-1.5 mr-1">Priority:</span>
            {['all', 'high', 'medium', 'low'].map((p) => (
              <button
                key={p}
                onClick={() => setPriorityFilter(p)}
                className={`px-2 py-1 text-[11px] font-bold uppercase rounded transition-colors ${
                  priorityFilter === p
                    ? 'bg-medpark-500 text-white shadow-2xs'
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
      <div className="divide-y divide-slate-100">
        {filteredItems.map((item) => {
          const isCompleted = item.status === 'completed';

          return (
            <div
              key={item.id}
              className={`p-4 space-y-2.5 transition-colors hover:bg-slate-50/60 ${
                isCompleted ? 'bg-slate-50/40 opacity-75' : ''
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start space-x-3 flex-1">
                  {/* Status Toggle Checkbox */}
                  <button
                    onClick={() => toggleItemStatus(item.id)}
                    className="mt-0.5 text-slate-400 hover:text-medpark-600 transition-colors"
                    title={isCompleted ? 'Mark as active' : 'Mark as completed'}
                  >
                    {isCompleted ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-600 fill-emerald-100" />
                    ) : (
                      <Circle className="w-5 h-5 text-slate-300 hover:text-medpark-500" />
                    )}
                  </button>

                  <div className="space-y-1 flex-1">
                    <div className="flex items-center space-x-2">
                      <span
                        className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-md border ${getPriorityBadge(
                          item.priority
                        )}`}
                      >
                        {item.priority} priority
                      </span>
                      <span className="text-xs font-bold text-slate-800 flex items-center space-x-1 bg-slate-100 px-2 py-0.5 rounded-md border border-slate-200">
                        <User className="w-3 h-3 text-slate-500" />
                        <span>{item.owner}</span>
                      </span>
                    </div>

                    <p
                      className={`text-sm font-semibold text-slate-900 leading-snug ${
                        isCompleted ? 'line-through text-slate-500' : ''
                      }`}
                    >
                      {item.task}
                    </p>
                  </div>
                </div>

                {/* Deadline tag */}
                <div className="flex flex-col items-end text-xs flex-shrink-0">
                  <div className="flex items-center space-x-1 text-slate-700 font-mono font-bold bg-slate-100 px-2 py-1 rounded-md border border-slate-200">
                    <Calendar className="w-3.5 h-3.5 text-medpark-600" />
                    <span>{item.deadline_date || item.deadline_phrase || 'Unspecified'}</span>
                  </div>
                  {item.deadline_phrase && item.deadline_date && (
                    <span className="text-[10px] text-slate-400 italic mt-0.5">
                      "{item.deadline_phrase}"
                    </span>
                  )}
                </div>
              </div>

              {/* Clickable Audio Evidence */}
              {item.evidence && item.evidence.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-0.5 pl-8">
                  {item.evidence.map((ev, idx) => (
                    <button
                      key={idx}
                      onClick={() => onSeek(ev.start, ev.end)}
                      className="inline-flex items-center space-x-1.5 text-xs text-medpark-800 bg-medpark-50 hover:bg-medpark-100 border border-medpark-200 px-2.5 py-1 rounded-lg transition-colors text-left group"
                      title="Click to play exact audio citation"
                    >
                      <Play className="w-3 h-3 fill-medpark-600 text-medpark-600 flex-shrink-0 group-hover:scale-110 transition-transform" />
                      <span className="font-mono font-bold text-[11px]">
                        [{Math.floor(ev.start)}s - {Math.floor(ev.end)}s]
                      </span>
                      <span className="italic truncate max-w-md text-slate-600">
                        "{ev.quote}"
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {filteredItems.length === 0 && (
          <div className="p-8 text-center text-sm text-slate-400">
            No action items match your search filter.
          </div>
        )}
      </div>
    </div>
  );
};
