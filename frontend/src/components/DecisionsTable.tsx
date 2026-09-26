import React, { useState } from 'react';
import { DecisionItem } from '../types';
import { useToast } from './Toast';
import { CheckCircle2, Play, Search, Copy, Filter, Sparkles, AlertTriangle, Circle } from 'lucide-react';

interface DecisionsTableProps {
  decisions: DecisionItem[];
  onSeek: (startSec: number, endSec?: number) => void;
  language?: 'all' | 'ro' | 'ru' | 'en';
}

const I18N = {
  all: {
    title: 'Clinical & Operational Decisions (Comparative View)',
    subtitle: 'Multi-language consensus with verified audio timestamps',
    reviewed: 'verified by reviewer',
    decisionsCount: 'decisions',
    copy: 'Copy',
    searchPlaceholder: 'Filter decisions across languages...',
    categories: {
      all: 'All',
      clinical: 'Clinical',
      budget: 'Budget',
      operations: 'Operations',
      protocol: 'Protocol',
    } as Record<string, string>,
    verifiedBadge: 'Verified',
    unverifiedBadge: 'Unverified',
    noEvidence: 'No audio evidence — verify manually',
    noDecisions: 'No decisions were extracted from this recording.',
    noMatch: 'No decisions match your search filter.',
    clearFilter: 'Clear filter',
  },
  ro: {
    title: 'Decizii Clinice și Operaționale Adoptate',
    subtitle: 'Consens verificat al consiliului medical cu marcaje temporale audio',
    reviewed: 'verificate de un recenzent',
    decisionsCount: 'decizii',
    copy: 'Copiază',
    searchPlaceholder: 'Filtrează deciziile după cuvinte cheie...',
    categories: {
      all: 'Toate',
      clinical: 'Clinic',
      budget: 'Buget',
      operations: 'Operațiuni',
      protocol: 'Protocol',
    } as Record<string, string>,
    verifiedBadge: 'Verificat',
    unverifiedBadge: 'Neverificat',
    noEvidence: 'Fără dovadă audio — verificați manual',
    noDecisions: 'Nicio decizie nu a fost extrasă din această înregistrare.',
    noMatch: 'Nicio decizie nu corespunde filtrului de căutare.',
    clearFilter: 'Resetează filtrul',
  },
  ru: {
    title: 'Принятые клинические и операционные решения',
    subtitle: 'Подтвержденный консенсус клинического совета с таймкодами аудио',
    reviewed: 'проверено рецензентом',
    decisionsCount: 'решений',
    copy: 'Копировать',
    searchPlaceholder: 'Поиск решений по ключевым словам...',
    categories: {
      all: 'Все',
      clinical: 'Клинические',
      budget: 'Бюджет',
      operations: 'Операции',
      protocol: 'Протокол',
    } as Record<string, string>,
    verifiedBadge: 'Проверено',
    unverifiedBadge: 'Не проверено',
    noEvidence: 'Нет аудио-метки — проверьте вручную',
    noDecisions: 'Из этой записи не было извлечено никаких решений.',
    noMatch: 'Нет решений, соответствующих условиям поиска.',
    clearFilter: 'Сбросить фильтр',
  },
  en: {
    title: 'Adopted Clinical & Operational Decisions',
    subtitle: 'Verified clinical council consensus with audio timestamps',
    reviewed: 'verified by a reviewer',
    decisionsCount: 'decisions',
    copy: 'Copy',
    searchPlaceholder: 'Filter decisions by keyword...',
    categories: {
      all: 'All',
      clinical: 'Clinical',
      budget: 'Budget',
      operations: 'Operations',
      protocol: 'Protocol',
    } as Record<string, string>,
    verifiedBadge: 'Verified',
    unverifiedBadge: 'Unverified',
    noEvidence: 'No audio evidence — verify manually',
    noDecisions: 'No decisions were extracted from this recording.',
    noMatch: 'No decisions match your search filter.',
    clearFilter: 'Clear filter',
  },
};

export const DecisionsTable: React.FC<DecisionsTableProps> = ({ decisions, onSeek, language = 'all' }) => {
  const { showToast } = useToast();
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const t = I18N[language] || I18N.all;

  const categories = ['all', 'clinical', 'budget', 'operations', 'protocol'];

  const filteredDecisions = decisions.filter((d) => {
    if (selectedCategory !== 'all' && d.category.toLowerCase() !== selectedCategory.toLowerCase()) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const localizedTopic = ((language === 'ru' && d.topic_ru) || (language === 'en' && d.topic_en) || d.topic).toLowerCase();
      const localizedDecision = ((language === 'ru' && d.decision_ru) || (language === 'en' && d.decision_en) || d.decision).toLowerCase();
      return (
        localizedDecision.includes(q) ||
        localizedTopic.includes(q) ||
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

  // Same timecode notation as the transcript viewer so citations read identically everywhere
  const formatTimestamp = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const reviewedCount = decisions.filter((d) => d.is_reviewed).length;

  const clearFilters = () => {
    setSelectedCategory('all');
    setSearchQuery('');
  };

  const handleCopyDecisions = () => {
    if (filteredDecisions.length === 0) return;
    const text = filteredDecisions
      .map((d, idx) => {
        const topic = (language === 'ru' && d.topic_ru) || (language === 'en' && d.topic_en) || d.topic;
        const dec = (language === 'ru' && d.decision_ru) || (language === 'en' && d.decision_en) || d.decision;
        return `${idx + 1}. [${(t.categories[d.category.toLowerCase()] || d.category).toUpperCase()}] ${topic}: ${dec}`;
      })
      .join('\n');

    navigator.clipboard.writeText(text);
    showToast('Copied to clipboard', `${filteredDecisions.length} decisions copied as text.`);
  };

  return (
    <section
      aria-labelledby="decisions-heading"
      className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden"
    >
      {/* Header Bar */}
      <div className="p-4 bg-slate-50/80 border-b border-slate-200 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center flex-shrink-0">
              <CheckCircle2 className="w-4 h-4" />
            </div>
            <div>
              <h3 id="decisions-heading" className="font-bold text-slate-900 text-sm">
                {t.title}
              </h3>
              <p className="text-xs text-slate-500">{t.subtitle}</p>
              <p className="text-[11px] font-medium text-slate-500 tabular-nums mt-0.5">
                {reviewedCount} / {decisions.length} {t.reviewed}
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <span
              role="status"
              className="text-xs font-semibold tabular-nums px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200"
            >
              {filteredDecisions.length} {t.decisionsCount}
            </span>
            <button
              onClick={handleCopyDecisions}
              disabled={filteredDecisions.length === 0}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-sm disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Copy decisions list to clipboard"
            >
              <Copy className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
              <span>{t.copy}</span>
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
              placeholder={t.searchPlaceholder}
              aria-label="Search decisions"
              className="w-full text-xs pl-9 pr-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/40 focus:border-medpark-500"
            />
          </div>

          <div
            role="group"
            aria-label="Filter by category"
            tabIndex={0}
            className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200 w-full sm:w-auto overflow-x-auto focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
          >
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                aria-pressed={selectedCategory === cat}
                className={`px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wide rounded transition-colors whitespace-nowrap focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 ${
                  selectedCategory === cat
                    ? 'bg-medpark-500 text-white'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {t.categories[cat] || cat}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Decisions List */}
      <div role="list" className="divide-y divide-slate-100">
        {filteredDecisions.map((d) => {
          const isGrounded = Boolean(d.evidence && d.evidence.length > 0);

          return (
            <div
              key={d.id}
              role="listitem"
              className={`p-4 space-y-2 hover:bg-slate-50/60 transition-colors border-l-4 ${
                isGrounded ? 'border-transparent' : 'border-amber-300'
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1.5 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold text-slate-700 bg-slate-100 px-2.5 py-0.5 rounded-md border border-slate-200">
                      {(language === 'ru' && d.topic_ru) || (language === 'en' && d.topic_en) || d.topic}
                    </span>
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md border ${getCategoryBadge(
                        d.category
                      )}`}
                    >
                      {t.categories[d.category.toLowerCase()] || d.category}
                    </span>
                    {/* Read-only record of the per-item human verification */}
                    {d.is_reviewed ? (
                      <span className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-md">
                        <CheckCircle2 className="w-3 h-3" aria-hidden="true" />
                        <span>{t.verifiedBadge}</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-md">
                        <Circle className="w-3 h-3" aria-hidden="true" />
                        <span>{t.unverifiedBadge}</span>
                      </span>
                    )}
                  </div>
                  <p className="text-sm font-semibold text-slate-900 leading-snug break-words">
                    {(language === 'ru' && d.decision_ru) || (language === 'en' && d.decision_en) || d.decision}
                  </p>
                </div>
              </div>

              {/* Clickable Audio Evidence Citations */}
              {isGrounded ? (
                <div className="flex flex-wrap gap-2 pt-1">
                  {d.evidence.map((ev, idx) => (
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
                <div className="pt-1">
                  <span className="inline-flex items-center space-x-1.5 text-[11px] font-bold text-amber-800 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-lg">
                    <AlertTriangle className="w-3 h-3" aria-hidden="true" />
                    <span>{t.noEvidence}</span>
                  </span>
                </div>
              )}
            </div>
          );
        })}

        {filteredDecisions.length === 0 && (
          <div className="p-8 text-center space-y-3">
            <p className="text-sm text-slate-600">
              {decisions.length === 0 ? t.noDecisions : t.noMatch}
            </p>
            {decisions.length > 0 && (
              <button
                onClick={clearFilters}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              >
                <Filter className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
                <span>{t.clearFilter}</span>
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
};
