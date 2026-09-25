import React from 'react';
import { DecisionItem } from '../types';
import { CheckCircle2, Play, Bookmark } from 'lucide-react';

interface DecisionsTableProps {
  decisions: DecisionItem[];
  onSeek: (startSec: number, endSec?: number) => void;
}

export const DecisionsTable: React.FC<DecisionsTableProps> = ({ decisions, onSeek }) => {
  const getCategoryBadge = (cat: string) => {
    switch (cat) {
      case 'clinical':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200';
      case 'budget':
        return 'bg-purple-50 text-purple-700 border-purple-200';
      case 'protocol':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="p-4 bg-slate-50/70 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-600" />
          <h3 className="font-semibold text-slate-900 text-sm">Adopted & Approved Decisions</h3>
        </div>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
          {decisions.length} decisions
        </span>
      </div>

      <div className="divide-y divide-slate-100">
        {decisions.map((d) => (
          <div key={d.id} className="p-4 space-y-2 hover:bg-slate-50/50 transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <div className="flex items-center space-x-2">
                  <span className="text-xs font-semibold text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
                    {d.topic}
                  </span>
                  <span
                    className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${getCategoryBadge(
                      d.category
                    )}`}
                  >
                    {d.category}
                  </span>
                </div>
                <p className="text-sm font-medium text-slate-900">{d.decision}</p>
              </div>
            </div>

            {/* Clickable Audio Evidence Citations */}
            {d.evidence && d.evidence.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {d.evidence.map((ev, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSeek(ev.start, ev.end)}
                    className="inline-flex items-center space-x-1.5 text-xs text-medpark-700 bg-medpark-50 hover:bg-medpark-100 border border-medpark-200 px-2.5 py-1 rounded-md transition-colors text-left"
                    title="Listen to audio evidence"
                  >
                    <Play className="w-3 h-3 fill-medpark-600 flex-shrink-0" />
                    <span className="font-mono font-medium">
                      [{Math.floor(ev.start)}s - {Math.floor(ev.end)}s]
                    </span>
                    <span className="italic truncate max-w-xs text-slate-600">
                      "{ev.quote}"
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}

        {decisions.length === 0 && (
          <div className="p-6 text-center text-sm text-slate-400">
            No decisions identified for this meeting.
          </div>
        )}
      </div>
    </div>
  );
};
