import React from 'react';
import { RiskOrQuestionItem } from '../types';
import { AlertTriangle, HelpCircle, Play, ShieldAlert } from 'lucide-react';

interface RisksQuestionsTableProps {
  items: RiskOrQuestionItem[];
  onSeek: (startSec: number, endSec?: number) => void;
}

export const RisksQuestionsTable: React.FC<RisksQuestionsTableProps> = ({
  items,
  onSeek,
}) => {
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

  const risks = items.filter((i) => i.item_type === 'risk');
  const questions = items.filter((i) => i.item_type === 'unresolved_question');

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden space-y-0">
      {/* Header */}
      <div className="p-4 bg-slate-50/70 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <ShieldAlert className="w-4 h-4 text-amber-600" />
          <h3 className="font-semibold text-slate-900 text-sm">
            Clinical Risks & Unresolved Questions
          </h3>
        </div>
        <div className="flex items-center space-x-2 text-xs">
          <span className="px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 font-medium">
            {risks.length} risks
          </span>
          <span className="px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 font-medium">
            {questions.length} questions
          </span>
        </div>
      </div>

      {/* Items list */}
      <div className="divide-y divide-slate-100">
        {items.map((item) => {
          const isRisk = item.item_type === 'risk';
          return (
            <div
              key={item.id}
              className="p-4 space-y-2 hover:bg-slate-50/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1.5 flex-1">
                  <div className="flex items-center space-x-2">
                    {isRisk ? (
                      <span className="inline-flex items-center space-x-1 text-xs font-semibold px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200">
                        <AlertTriangle className="w-3 h-3" />
                        <span>Identified Risk</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center space-x-1 text-xs font-semibold px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                        <HelpCircle className="w-3 h-3" />
                        <span>Unresolved Question</span>
                      </span>
                    )}

                    <span
                      className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${getSeverityBadge(
                        item.severity
                      )}`}
                    >
                      Severity: {item.severity}
                    </span>
                  </div>

                  <p className="text-sm font-medium text-slate-900">
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
                      className="inline-flex items-center space-x-1.5 text-xs text-medpark-700 bg-medpark-50 hover:bg-medpark-100 border border-medpark-200 px-2.5 py-1 rounded-md transition-colors text-left"
                      title="Listen to audio evidence for this item"
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
          );
        })}

        {items.length === 0 && (
          <div className="p-6 text-center text-sm text-slate-400">
            No major clinical risks or unresolved questions identified in this meeting.
          </div>
        )}
      </div>
    </div>
  );
};
