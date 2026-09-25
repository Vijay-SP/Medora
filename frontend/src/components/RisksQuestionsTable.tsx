import React, { useState } from 'react';
import { RiskOrQuestionItem } from '../types';
import { useToast } from './Toast';
import { AlertTriangle, HelpCircle, Play, ShieldAlert, Search, Copy } from 'lucide-react';

interface RisksQuestionsTableProps {
  items: RiskOrQuestionItem[];
  onSeek: (startSec: number, endSec?: number) => void;
}

export const RisksQuestionsTable: React.FC<RisksQuestionsTableProps> = ({
  items,
  onSeek,
}) => {
  const { showToast } = useToast();
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<'all' | 'risk' | 'unresolved_question'>('all');

  const filteredItems = items.filter((item) => {
    if (typeFilter !== 'all' && item.item_type !== typeFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return item.description.toLowerCase().includes(q) || item.severity.toLowerCase().includes(q);
    }
    return true;
  });

  const getSeverityBadge = (sev: string) => {
    switch (sev.toLowerCase()) {
      case 'high':
        return 'bg-rose-50 text-rose-700 border-rose-200';
      case 'medium':
        return 'bg-amber-50 text-amber-700 border-amber-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  const handleCopyItems = () => {
    if (filteredItems.length === 0) return;
    const text = filteredItems
      .map(
        (i, idx) =>
          `${idx + 1}. [${i.item_type.toUpperCase()}] Severity: ${i.severity.toUpperCase()} | ${
            i.description
          }`
      )
      .join('\n');

    navigator.clipboard.writeText(text);
    showToast('Copied to clipboard', `${filteredItems.length} items copied to clipboard.`);
  };

  const risksCount = items.filter((i) => i.item_type === 'risk').length;
  const questionsCount = items.filter((i) => i.item_type === 'unresolved_question').length;

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
      {/* Header */}
      <div className="p-4 bg-slate-50/80 border-b border-slate-200 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-lg bg-amber-100 text-amber-800 flex items-center justify-center">
              <ShieldAlert className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 text-sm">Clinical Risks & Open Questions</h3>
              <p className="text-xs text-slate-500">Identified clinical safety risks and unresolved queries</p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <span className="px-2.5 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 text-xs font-semibold">
              {risksCount} risks
            </span>
            <span className="px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 text-xs font-semibold">
              {questionsCount} questions
            </span>
            <button
              onClick={handleCopyItems}
              disabled={filteredItems.length === 0}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-2xs disabled:opacity-50"
              title="Copy list to clipboard"
            >
              <Copy className="w-3.5 h-3.5 text-slate-500" />
              <span>Copy</span>
            </button>
          </div>
        </div>

        {/* Filter bar */}
        <div className="flex flex-col sm:flex-row items-center gap-2 pt-1">
          <div className="relative flex-1 w-full">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter risks & questions..."
              className="w-full text-xs pl-9 pr-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
          </div>

          <div className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200 w-full sm:w-auto">
            <button
              onClick={() => setTypeFilter('all')}
              className={`px-2.5 py-1 text-[11px] font-bold uppercase rounded transition-colors ${
                typeFilter === 'all'
                  ? 'bg-medpark-500 text-white shadow-2xs'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setTypeFilter('risk')}
              className={`px-2.5 py-1 text-[11px] font-bold uppercase rounded transition-colors ${
                typeFilter === 'risk'
                  ? 'bg-medpark-500 text-white shadow-2xs'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              Risks
            </button>
            <button
              onClick={() => setTypeFilter('unresolved_question')}
              className={`px-2.5 py-1 text-[11px] font-bold uppercase rounded transition-colors ${
                typeFilter === 'unresolved_question'
                  ? 'bg-medpark-500 text-white shadow-2xs'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              Questions
            </button>
          </div>
        </div>
      </div>

      {/* Items list */}
      <div className="divide-y divide-slate-100">
        {filteredItems.map((item) => {
          const isRisk = item.item_type === 'risk';
          return (
            <div key={item.id} className="p-4 space-y-2 hover:bg-slate-50/60 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1.5 flex-1">
                  <div className="flex items-center space-x-2">
                    {isRisk ? (
                      <span className="inline-flex items-center space-x-1 text-xs font-bold px-2.5 py-0.5 rounded-md bg-rose-50 text-rose-700 border border-rose-200">
                        <AlertTriangle className="w-3 h-3" />
                        <span>Identified Risk</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center space-x-1 text-xs font-bold px-2.5 py-0.5 rounded-md bg-amber-50 text-amber-700 border border-amber-200">
                        <HelpCircle className="w-3 h-3" />
                        <span>Unresolved Question</span>
                      </span>
                    )}

                    <span
                      className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-md border ${getSeverityBadge(
                        item.severity
                      )}`}
                    >
                      Severity: {item.severity}
                    </span>
                  </div>

                  <p className="text-sm font-semibold text-slate-900 leading-snug">
                    {item.description}
                  </p>
                </div>
              </div>

              {/* Clickable Audio Evidence */}
              {item.evidence && item.evidence.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
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
            No risks or unresolved questions match your filter.
          </div>
        )}
      </div>
    </div>
  );
};
