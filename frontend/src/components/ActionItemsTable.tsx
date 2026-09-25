import React, { useState } from 'react';
import { ActionItem } from '../types';
import { ListTodo, Play, Calendar, User, Clock, AlertCircle } from 'lucide-react';

interface ActionItemsTableProps {
  actionItems: ActionItem[];
  onSeek: (startSec: number, endSec?: number) => void;
}

export const ActionItemsTable: React.FC<ActionItemsTableProps> = ({
  actionItems,
  onSeek,
}) => {
  const [filter, setFilter] = useState<'all' | 'open' | 'completed'>('all');

  const filteredItems = actionItems.filter((item) => {
    if (filter === 'open') return item.status !== 'completed';
    if (filter === 'completed') return item.status === 'completed';
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

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Header & Filter Bar */}
      <div className="p-4 bg-slate-50/70 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center space-x-2">
          <ListTodo className="w-4 h-4 text-medpark-600" />
          <h3 className="font-semibold text-slate-900 text-sm">Action Items & Task Plan</h3>
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-medpark-50 text-medpark-700 border border-medpark-200">
            {actionItems.length}
          </span>
        </div>

        {/* Filters */}
        <div className="flex items-center space-x-1 text-xs">
          <button
            onClick={() => setFilter('all')}
            className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
              filter === 'all'
                ? 'bg-medpark-500 text-white shadow-xs'
                : 'text-slate-600 hover:bg-slate-200/60'
            }`}
          >
            All ({actionItems.length})
          </button>
          <button
            onClick={() => setFilter('open')}
            className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
              filter === 'open'
                ? 'bg-medpark-500 text-white shadow-xs'
                : 'text-slate-600 hover:bg-slate-200/60'
            }`}
          >
            Active
          </button>
          <button
            onClick={() => setFilter('completed')}
            className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
              filter === 'completed'
                ? 'bg-medpark-500 text-white shadow-xs'
                : 'text-slate-600 hover:bg-slate-200/60'
            }`}
          >
            Completed
          </button>
        </div>
      </div>

      {/* Action Items List */}
      <div className="divide-y divide-slate-100">
        {filteredItems.map((item) => (
          <div key={item.id} className="p-4 space-y-3 hover:bg-slate-50/50 transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1.5 flex-1">
                <div className="flex items-center space-x-2">
                  <span
                    className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${getPriorityBadge(
                      item.priority
                    )}`}
                  >
                    {item.priority}
                  </span>
                  <span className="text-xs font-semibold text-slate-700 flex items-center space-x-1">
                    <User className="w-3 h-3 text-slate-400" />
                    <span>{item.owner}</span>
                  </span>
                </div>
                <p className="text-sm font-medium text-slate-900">{item.task}</p>
              </div>

              {/* Deadline Tag */}
              <div className="flex flex-col items-end text-xs">
                <div className="flex items-center space-x-1 text-slate-600 font-mono">
                  <Calendar className="w-3.5 h-3.5 text-medpark-500" />
                  <span>{item.deadline_date || item.deadline_phrase || 'Unspecified'}</span>
                </div>
                {item.deadline_phrase && item.deadline_date && (
                  <span className="text-[10px] text-slate-400 italic">
                    "{item.deadline_phrase}"
                  </span>
                )}
              </div>
            </div>

            {/* Clickable Audio Evidence */}
            {item.evidence && item.evidence.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {item.evidence.map((ev, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSeek(ev.start, ev.end)}
                    className="inline-flex items-center space-x-1.5 text-xs text-medpark-700 bg-medpark-50 hover:bg-medpark-100 border border-medpark-200 px-2.5 py-1 rounded-md transition-colors text-left"
                    title="Listen to audio evidence for this task"
                  >
                    <Play className="w-3 h-3 fill-medpark-600 flex-shrink-0" />
                    <span className="font-mono font-medium">
                      [{Math.floor(ev.start)}s - {Math.floor(ev.end)}s]
                    </span>
                    <span className="italic truncate max-w-sm text-slate-600">
                      "{ev.quote}"
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}

        {filteredItems.length === 0 && (
          <div className="p-6 text-center text-sm text-slate-400">
            No action items found for this filter.
          </div>
        )}
      </div>
    </div>
  );
};
