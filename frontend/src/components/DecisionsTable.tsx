import React, { useState } from 'react';
import { DecisionItem } from '../types';
import { useToast } from './Toast';
import { CheckCircle2, Play, Search, Copy, Filter, Sparkles } from 'lucide-react';

interface DecisionsTableProps {
  decisions: DecisionItem[];
  onSeek: (startSec: number, endSec?: number) => void;
}

export const DecisionsTable: React.FC<DecisionsTableProps> = ({ decisions, onSeek }) => {
  const { showToast } = useToast();
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');

  const categories = ['all', 'clinical', 'budget', 'operations', 'protocol'];

  const filteredDecisions = decisions.filter((d) => {
    if (selectedCategory !== 'all' && d.category.toLowerCase() !== selectedCategory.toLowerCase()) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        d.decision.toLowerCase().includes(q) ||
        d.topic.toLowerCase().includes(q) ||
        d.category.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const getCategoryBadge = (cat: string) => {
    switch (cat.toLowerCase()) {
      case 'clinical':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200';
      case 'budget':
        return 'bg-purple-50 text-purple-700 border-purple-200';
      case 'protocol':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      case 'operations':
        return 'bg-amber-50 text-amber-700 border-amber-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  const handleCopyDecisions = () => {
    if (filteredDecisions.length === 0) return;
    const text = filteredDecisions
      .map((d, idx) => `${idx + 1}. [${d.category.toUpperCase()}] ${d.topic}: ${d.decision}`)
      .join('\n');

    navigator.clipboard.writeText(text);
    showToast('Copied to clipboard', `${filteredDecisions.length} decisions copied as text.`);
  };

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
      {/* Header Bar */}
      <div className="p-4 bg-slate-50/80 border-b border-slate-200 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center">
              <CheckCircle2 className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 text-sm">Adopted Clinical & Operational Decisions</h3>
              <p className="text-xs text-slate-500">Verified clinical council consensus with audio timestamps</p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
              {filteredDecisions.length} decisions
            </span>
            <button
              onClick={handleCopyDecisions}
              disabled={filteredDecisions.length === 0}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-2xs disabled:opacity-50"
              title="Copy decisions list to clipboard"
            >
              <Copy className="w-3.5 h-3.5 text-slate-500" />
              <span>Copy</span>
            </button>
          </div>
        </div>

        {/* Search & Category Filter Bar */}
        <div className="flex flex-col sm:flex-row items-center gap-2 pt-1">
          <div className="relative flex-1 w-full">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter decisions by keyword..."
              className="w-full text-xs pl-9 pr-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
          </div>

          <div className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200 w-full sm:w-auto overflow-x-auto">
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-2.5 py-1 text-[11px] font-bold uppercase rounded transition-colors whitespace-nowrap ${
                  selectedCategory === cat
                    ? 'bg-medpark-500 text-white shadow-2xs'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Decisions List */}
      <div className="divide-y divide-slate-100">
        {filteredDecisions.map((d) => (
          <div key={d.id} className="p-4 space-y-2 hover:bg-slate-50/60 transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <div className="flex items-center space-x-2">
                  <span className="text-xs font-bold text-slate-700 bg-slate-100 px-2.5 py-0.5 rounded-md border border-slate-200">
                    {d.topic}
                  </span>
                  <span
                    className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-md border ${getCategoryBadge(
                      d.category
                    )}`}
                  >
                    {d.category}
                  </span>
                </div>
                <p className="text-sm font-semibold text-slate-900 leading-snug">{d.decision}</p>
              </div>
            </div>

            {/* Clickable Audio Evidence Citations */}
            {d.evidence && d.evidence.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {d.evidence.map((ev, idx) => (
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
        ))}

        {filteredDecisions.length === 0 && (
          <div className="p-8 text-center text-sm text-slate-400">
            No decisions match your search filter.
          </div>
        )}
      </div>
    </div>
  );
};
