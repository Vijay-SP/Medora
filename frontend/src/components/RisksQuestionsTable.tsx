import React, { useState } from 'react';
import { RiskOrQuestionItem } from '../types';
import { useToast } from './Toast';
import { AlertTriangle, HelpCircle, Play, ShieldAlert, Search, Copy, Filter, MicOff } from 'lucide-react';

interface RisksQuestionsTableProps {
  items: RiskOrQuestionItem[];
  onSeek: (startSec: number, endSec?: number) => void;
  language?: 'all' | 'ro' | 'ru' | 'en';
}

const I18N = {
  all: {
    title: 'Clinical Risks & Open Questions (Comparative View)',
    subtitle: 'Identified clinical safety risks and unresolved queries (RO / RU / EN)',
    risksCount: 'risks',
    questionsCount: 'questions',
    copy: 'Copy',
    searchPlaceholder: 'Filter risks and questions across languages...',
    types: {
      all: 'All',
      risk: 'Risks',
      unresolved_question: 'Questions',
    } as Record<string, string>,
    auditBadge: 'Audit notice',
    riskBadge: 'Identified Risk',
    questionBadge: 'Unresolved Question',
    unverifiedAudio: 'Not verified against audio',
    severityPrefix: 'Severity:',
    severities: {
      high: 'High',
      medium: 'Medium',
      low: 'Low',
    } as Record<string, string>,
    noEvidence: 'No audio evidence — verify manually',
    noItems: 'No clinical risks or unresolved questions were raised.',
    noMatch: 'No risks or unresolved questions match your filter.',
    clearFilter: 'Clear filter',
  },
  ro: {
    title: 'Riscuri Clinice și Întrebări Deschise',
    subtitle: 'Riscuri identificate pentru siguranța pacienților și întrebări nerezolvate',
    risksCount: 'riscuri',
    questionsCount: 'întrebări',
    copy: 'Copiază',
    searchPlaceholder: 'Filtrează riscurile și întrebările...',
    types: {
      all: 'Toate',
      risk: 'Riscuri',
      unresolved_question: 'Întrebări',
    } as Record<string, string>,
    auditBadge: 'Notă de audit',
    riskBadge: 'Risc Identificat',
    questionBadge: 'Întrebare Nerezolvată',
    unverifiedAudio: 'Neverificat pe baza înregistrării',
    severityPrefix: 'Severitate:',
    severities: {
      high: 'Ridicată',
      medium: 'Medie',
      low: 'Scăzută',
    } as Record<string, string>,
    noEvidence: 'Fără dovadă audio — verificați manual',
    noItems: 'Nu au fost identificate riscuri clinice sau întrebări deschise.',
    noMatch: 'Niciun risc sau întrebare nu corespunde filtrului selectat.',
    clearFilter: 'Resetează filtrul',
  },
  ru: {
    title: 'Клинические риски и открытые вопросы',
    subtitle: 'Выявленные риски безопасности и нерешенные вопросы заседания',
    risksCount: 'рисков',
    questionsCount: 'вопросов',
    copy: 'Копировать',
    searchPlaceholder: 'Поиск рисков и вопросов...',
    types: {
      all: 'Все',
      risk: 'Риски',
      unresolved_question: 'Вопросы',
    } as Record<string, string>,
    auditBadge: 'Аудиторская заметка',
    riskBadge: 'Выявленный риск',
    questionBadge: 'Нерешенный вопрос',
    unverifiedAudio: 'Не проверено по аудиозаписи',
    severityPrefix: 'Серьезность:',
    severities: {
      high: 'Высокая',
      medium: 'Средняя',
      low: 'Низкая',
    } as Record<string, string>,
    noEvidence: 'Нет аудио-метки — проверьте вручную',
    noItems: 'Клинических рисков или открытых вопросов не зафиксировано.',
    noMatch: 'Нет записей, соответствующих выбранному фильтру.',
    clearFilter: 'Сбросить фильтр',
  },
  en: {
    title: 'Clinical Risks & Open Questions',
    subtitle: 'Identified clinical safety risks and unresolved queries',
    risksCount: 'risks',
    questionsCount: 'questions',
    copy: 'Copy',
    searchPlaceholder: 'Filter risks and questions...',
    types: {
      all: 'All',
      risk: 'Risks',
      unresolved_question: 'Questions',
    } as Record<string, string>,
    auditBadge: 'Audit notice',
    riskBadge: 'Identified Risk',
    questionBadge: 'Unresolved Question',
    unverifiedAudio: 'Not verified against audio',
    severityPrefix: 'Severity:',
    severities: {
      high: 'High',
      medium: 'Medium',
      low: 'Low',
    } as Record<string, string>,
    noEvidence: 'No audio evidence — verify manually',
    noItems: 'No clinical risks or unresolved questions were raised in this meeting.',
    noMatch: 'No risks or unresolved questions match your filter.',
    clearFilter: 'Clear filter',
  },
};

export const RisksQuestionsTable: React.FC<RisksQuestionsTableProps> = ({
  items,
  onSeek,
  language = 'all',
}) => {
  const { showToast } = useToast();
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<'all' | 'risk' | 'unresolved_question'>('all');
  const t = I18N[language] || I18N.all;

  // Visible labels mapped to the backend vocabulary so the filter cannot drift from the enum
  const typeFilters: { value: 'all' | 'risk' | 'unresolved_question'; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'risk', label: 'Risks' },
    { value: 'unresolved_question', label: 'Questions' },
  ];

  const filteredItems = items.filter((item) => {
    if (typeFilter !== 'all' && item.item_type !== typeFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const localizedDesc = ((language === 'ru' && item.description_ru) || (language === 'en' && item.description_en) || item.description).toLowerCase();
      return localizedDesc.includes(q) || item.description.toLowerCase().includes(q) || item.severity.toLowerCase().includes(q);
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

  // Same timecode notation as the transcript viewer so citations read identically everywhere
  const formatTimestamp = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  // The backend writes two degraded-extraction markers in Romanian into this list.
  // They must never read as ordinary rows, and the Romanian text must not be the only cue.
  const isAuditNote = (description: string) => /^\s*NOT[ĂA]\s+AUDIT/i.test(description);
  const isUngroundedClaim = (description: string) => description.includes('[NEVERIFICAT AUDIO]');

  const degradedCount = items.filter(
    (i) => isAuditNote(i.description) || isUngroundedClaim(i.description)
  ).length;

  const clearFilters = () => {
    setTypeFilter('all');
    setSearchQuery('');
  };

  const handleCopyItems = () => {
    if (filteredItems.length === 0) return;
    const text = filteredItems
      .map((i, idx) => {
        const desc = (language === 'ru' && i.description_ru) || (language === 'en' && i.description_en) || i.description;
        const typeLabel = t.types[i.item_type] || i.item_type;
        const sev = t.severities[i.severity] || i.severity;
        return `${idx + 1}. [${typeLabel.toUpperCase()}] ${t.severityPrefix} ${sev} | ${desc}`;
      })
      .join('\n');

    navigator.clipboard.writeText(text);
    showToast('Copied to clipboard', `${filteredItems.length} items copied to clipboard.`);
  };

  const risksCount = items.filter((i) => i.item_type === 'risk').length;
  const questionsCount = items.filter((i) => i.item_type === 'unresolved_question').length;

  return (
    <section
      aria-labelledby="risks-heading"
      className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden"
    >
      {/* Header */}
      <div className="p-4 bg-slate-50/80 border-b border-slate-200 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-lg bg-amber-100 text-amber-800 flex items-center justify-center flex-shrink-0">
              <ShieldAlert className="w-4 h-4" />
            </div>
            <div>
              <h3 id="risks-heading" className="font-bold text-slate-900 text-sm">
                {t.title}
              </h3>
              <p className="text-xs text-slate-500">{t.subtitle}</p>
              {degradedCount > 0 && (
                <p className="text-[11px] font-bold text-rose-700 tabular-nums mt-0.5">
                  {degradedCount} extraction {degradedCount === 1 ? 'warning' : 'warnings'} require manual review
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <span
              role="status"
              className="px-2.5 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 text-xs font-semibold tabular-nums"
            >
              {risksCount} {t.risksCount}
            </span>
            <span
              role="status"
              className="px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 text-xs font-semibold tabular-nums"
            >
              {questionsCount} {t.questionsCount}
            </span>
            <button
              onClick={handleCopyItems}
              disabled={filteredItems.length === 0}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-sm disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Copy list to clipboard"
            >
              <Copy className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
              <span>{t.copy}</span>
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
              placeholder={t.searchPlaceholder}
              aria-label="Search risks and open questions"
              className="w-full text-xs pl-9 pr-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/40 focus:border-medpark-500"
            />
          </div>

          <div
            role="group"
            aria-label="Filter by item type"
            className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200 w-full sm:w-auto"
          >
            {typeFilters.map((f) => (
              <button
                key={f.value}
                onClick={() => setTypeFilter(f.value)}
                aria-pressed={typeFilter === f.value}
                className={`px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wide rounded transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 ${
                  typeFilter === f.value
                    ? 'bg-medpark-500 text-white'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {t.types[f.value] || f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Items list */}
      <div role="list" className="divide-y divide-slate-100">
        {filteredItems.map((item) => {
          const isRisk = item.item_type === 'risk';
          const auditNote = isAuditNote(item.description);
          const ungrounded = isUngroundedClaim(item.description);
          const isDegraded = auditNote || ungrounded;
          const isGrounded = Boolean(item.evidence && item.evidence.length > 0);

          return (
            <div
              key={item.id}
              role="listitem"
              className={`p-4 space-y-2 transition-colors border-l-4 ${
                isDegraded
                  ? 'bg-rose-50/50 border-rose-500 hover:bg-rose-50'
                  : `hover:bg-slate-50/60 ${isGrounded ? 'border-transparent' : 'border-amber-300'}`
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1.5 flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {auditNote ? (
                      <span className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-rose-600 text-white border border-rose-600">
                        <ShieldAlert className="w-3 h-3" aria-hidden="true" />
                        <span>{t.auditBadge}</span>
                      </span>
                    ) : isRisk ? (
                      <span className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-rose-50 text-rose-700 border border-rose-200">
                        <AlertTriangle className="w-3 h-3" aria-hidden="true" />
                        <span>{t.riskBadge}</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 border border-amber-200">
                        <HelpCircle className="w-3 h-3" aria-hidden="true" />
                        <span>{t.questionBadge}</span>
                      </span>
                    )}

                    {ungrounded && (
                      <span className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-rose-600 text-white border border-rose-600">
                        <MicOff className="w-3 h-3" aria-hidden="true" />
                        <span>{t.unverifiedAudio}</span>
                      </span>
                    )}

                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md border ${getSeverityBadge(
                        item.severity
                      )}`}
                    >
                      {t.severityPrefix} {t.severities[item.severity] || item.severity}
                    </span>
                  </div>

                  {/* English lead so the Romanian marker is never the only cue */}
                  {auditNote && (
                    <p className="text-sm font-bold text-rose-800 leading-snug">
                      Degraded extraction: the neural model did not run. Review every item in these minutes before
                      approval.
                    </p>
                  )}
                  {ungrounded && (
                    <p className="text-sm font-bold text-rose-800 leading-snug">
                      Claim demoted: no synchronised audio evidence was found for this statement.
                    </p>
                  )}

                  <p
                    className={`text-sm leading-snug break-words ${
                      isDegraded ? 'text-slate-700' : 'font-semibold text-slate-900'
                    }`}
                    lang={isDegraded ? 'ro' : undefined}
                  >
                    {(language === 'ru' && item.description_ru) || (language === 'en' && item.description_en) || item.description}
                  </p>
                </div>
              </div>

              {/* Clickable Audio Evidence */}
              {isGrounded ? (
                <div className="flex flex-wrap gap-2 pt-1">
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
                // The degraded rows already carry a stronger, explicit warning above
                !isDegraded && (
                  <div className="pt-1">
                    <span className="inline-flex items-center space-x-1.5 text-[11px] font-bold text-amber-800 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-lg">
                      <AlertTriangle className="w-3 h-3" aria-hidden="true" />
                      <span>{t.noEvidence}</span>
                    </span>
                  </div>
                )
              )}
            </div>
          );
        })}

        {filteredItems.length === 0 && (
          <div className="p-8 text-center space-y-3">
            <p className="text-sm text-slate-600">
              {items.length === 0 ? t.noItems : t.noMatch}
            </p>
            {items.length > 0 && (
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
