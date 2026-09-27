import React, { useState, useEffect, useRef, useMemo } from 'react';
import { TranscriptSegment, LanguageSpan, getSegmentDisplayText } from '../types';
import { useToast } from './Toast';
import {
  Play,
  Edit2,
  Check,
  X,
  AlertTriangle,
  Search,
  Filter,
  Copy,
  Radio,
  Sparkles,
  Loader2,
} from 'lucide-react';

interface TranscriptViewerProps {
  segments: TranscriptSegment[];
  onSeek: (seconds: number) => void;
  onUpdateSegment: (segmentId: string, correctedText: string) => Promise<void>;
  currentTime?: number;
}

// Display order of language codes in the filter bar; unknown codes sort after the known ones.
const LANGUAGE_ORDER = ['ro', 'ru', 'en', 'mixed', 'und'];
const languageRank = (lang: string) => {
  const i = LANGUAGE_ORDER.indexOf(lang);
  return i === -1 ? LANGUAGE_ORDER.length : i;
};

// Unique span languages of a mixed segment in order of first appearance ("RO·RU").
const spanLanguages = (spans?: LanguageSpan[]) =>
  Array.from(new Set((spans || []).map((s) => s.language.toLowerCase())));

// Chip text. Never colour-only: RO / RU / EN / RO·RU (mixed, from its spans) / ?? (undetermined).
const getLanguageLabel = (lang: string, spans?: LanguageSpan[]) => {
  const code = (lang || 'und').toLowerCase();
  if (code === 'mixed') {
    const parts = spanLanguages(spans);
    return parts.length > 0 ? parts.map((p) => p.toUpperCase()).join('·') : 'MIXED';
  }
  if (code === 'und') return '??';
  return code.toUpperCase();
};

const getLanguageAriaLabel = (lang: string) => {
  switch ((lang || 'und').toLowerCase()) {
    case 'ro':
      return 'Romanian';
    case 'ru':
      return 'Russian';
    case 'en':
      return 'English';
    case 'mixed':
      return 'Mixed languages';
    case 'und':
      return 'Undetermined language';
    default:
      return lang.toUpperCase();
  }
};

const describeSpans = (spans?: LanguageSpan[]) =>
  (spans || []).map((s) => `${s.language.toUpperCase()} ${s.start.toFixed(1)}–${s.end.toFixed(1)} s`).join(', ') ||
  'no span detail';

export const TranscriptViewer: React.FC<TranscriptViewerProps> = ({
  segments,
  onSeek,
  onUpdateSegment,
  currentTime = 0,
}) => {
  const { showToast } = useToast();

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedLanguage, setSelectedLanguage] = useState<string>('all');
  const [selectedSpeaker, setSelectedSpeaker] = useState<string>('all');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);

  // Segment editing state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const activeSegmentRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  // Optimization: Memoize unique speakers list to avoid recreating set and array on every time update (60fps audio progress)
  const speakers = useMemo(() => Array.from(new Set(segments.map((s) => s.speaker))), [segments]);

  // Optimization: Memoize languages list to prevent recalculating unique languages and sorting on every render
  const languagesPresent = useMemo(
    () =>
      Array.from(new Set(segments.map((s) => (s.language || 'und').toLowerCase()))).sort(
        (a, b) => languageRank(a) - languageRank(b) || a.localeCompare(b)
      ),
    [segments]
  );

  // A pill selected for a language that no longer exists (segments reloaded) must not blank the list.
  const effectiveLanguage = selectedLanguage !== 'all' && !languagesPresent.includes(selectedLanguage) ? 'all' : selectedLanguage;

  // Determine active segment based on current playback time
  const activeSegmentId = segments.find(
    (s) => currentTime >= s.start && currentTime <= s.end
  )?.id;

  // Auto-scroll to active segment if enabled
  useEffect(() => {
    if (autoScroll && activeSegmentRef.current) {
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      activeSegmentRef.current.scrollIntoView({
        behavior: reduce ? 'auto' : 'smooth',
        block: 'nearest',
      });
    }
  }, [activeSegmentId, autoScroll]);

  // Keyboard shortcut '/' to focus search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== '/') return;
      const el = document.activeElement as HTMLElement | null;
      if (el?.tagName === 'INPUT' || el?.tagName === 'TEXTAREA' || el?.tagName === 'SELECT' || el?.isContentEditable) {
        return;
      }
      // Never steal focus out of an open dialog onto a search box behind its overlay
      if (document.querySelector('[role="dialog"]')) return;
      if (searchInputRef.current?.offsetParent) {
        e.preventDefault();
        searchInputRef.current.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Optimization: Memoize filtered segments so playback time updates do not re-run filtering/string searches unnecessarily
  const filteredSegments = useMemo(() => {
    return segments.filter((seg) => {
      // Language filter
      if (effectiveLanguage !== 'all' && (seg.language || 'und').toLowerCase() !== effectiveLanguage) {
        return false;
      }
      // Speaker filter
      if (selectedSpeaker !== 'all' && seg.speaker !== selectedSpeaker) {
        return false;
      }
      // Search query filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const text = getSegmentDisplayText(seg).toLowerCase();
        const speaker = seg.speaker.toLowerCase();
        return text.includes(q) || speaker.includes(q);
      }
      return true;
    });
  }, [segments, effectiveLanguage, selectedSpeaker, searchQuery]);

  const startEdit = (seg: TranscriptSegment) => {
    setEditingId(seg.id);
    setEditText(getSegmentDisplayText(seg));
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditText('');
  };

  const saveEdit = async (segId: string) => {
    setIsSaving(true);
    try {
      await onUpdateSegment(segId, editText.trim());
      setEditingId(null);
      showToast('Transcript updated', 'The corrected utterance was saved successfully.');
    } catch (err) {
      console.error('Failed to save correction:', err);
      showToast('Save failed', 'Could not save transcript correction.', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCopyTranscript = () => {
    if (filteredSegments.length === 0) return;
    const text = filteredSegments
      .map(
        (s) =>
          `[${formatTimestamp(s.start)} - ${formatTimestamp(s.end)}] ${s.speaker} (${getLanguageLabel(
            s.language,
            s.language_spans
          )}): ${getSegmentDisplayText(s)}`
      )
      .join('\n');

    navigator.clipboard.writeText(text);
    showToast('Copied to clipboard', `${filteredSegments.length} utterances copied as formatted transcript.`);
  };

  const formatTimestamp = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  // Colour is a secondary cue only: every chip also carries a distinct text label (see getLanguageLabel).
  const getLanguageColor = (lang: string) => {
    switch ((lang || 'und').toLowerCase()) {
      case 'ro':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      case 'ru':
        return 'bg-amber-50 text-amber-700 border-amber-200';
      case 'en':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200';
      case 'mixed':
        return 'bg-violet-50 text-violet-700 border-violet-300 border-dashed';
      case 'und':
        return 'bg-slate-100 text-slate-500 border-slate-300 border-dotted';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  // Tooltip for the language chip: how the language was decided and how sure the restricted LID was.
  const getLanguageTitle = (seg: TranscriptSegment) => {
    const lang = (seg.language || 'und').toLowerCase();
    const base =
      lang === 'mixed'
        ? `Code-switched utterance: ${describeSpans(seg.language_spans)}`
        : lang === 'und'
        ? 'Language undetermined (too little speech for identification)'
        : `Language ${getLanguageLabel(lang)}`;
    const source = seg.language_source ? `, source: ${seg.language_source}` : '';
    const conf =
      typeof seg.language_confidence === 'number' && seg.language_confidence > 0
        ? `, confidence ${Math.round(seg.language_confidence * 100)}%`
        : '';
    return `${base}${source}${conf}`;
  };

  const renderHighlightedText = (text: string, query: string) => {
    if (!query.trim()) return text;
    const parts = text.split(new RegExp(`(${query.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&')})`, 'gi'));
    return parts.map((part, i) =>
      part.toLowerCase() === query.toLowerCase() ? (
        <mark key={i} className="bg-amber-200 text-amber-900 rounded-sm px-0.5 font-medium">
          {part}
        </mark>
      ) : (
        part
      )
    );
  };

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden divide-y divide-slate-100">

      {/* Header & Controls Bar */}
      <div className="p-4 bg-slate-50/80 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h3 className="font-bold text-slate-900 text-sm flex items-center space-x-2">
              <span>Synchronized Multilingual Transcript</span>
              <span className="text-[10px] font-semibold tabular-nums px-2 py-0.5 rounded-full bg-medpark-50 text-medpark-700 border border-medpark-500/20">
                {filteredSegments.length} of {segments.length} utterances
              </span>
            </h3>
            <p className="text-xs text-slate-500">
              Click timestamps to listen. Press <kbd className="font-mono bg-white px-1 border rounded text-[10px]">/</kbd> to search transcript.
            </p>
          </div>

          <div className="flex items-center space-x-2">
            {/* Auto-scroll toggle */}
            <button
              onClick={() => setAutoScroll(!autoScroll)}
              aria-pressed={autoScroll}
              className={`inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 ${
                autoScroll
                  ? 'bg-medpark-50 border-medpark-500/30 text-medpark-700'
                  : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-100'
              }`}
              title="Toggle auto-scrolling to active audio segment"
            >
              <Radio className={`w-3.5 h-3.5 ${autoScroll ? 'text-medpark-600' : 'text-slate-400'}`} />
              <span>{autoScroll ? 'Auto-Sync On' : 'Auto-Sync Off'}</span>
            </button>

            {/* Copy Transcript */}
            <button
              onClick={handleCopyTranscript}
              disabled={filteredSegments.length === 0}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition-colors shadow-sm disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Copy visible transcript text to clipboard"
            >
              <Copy className="w-3.5 h-3.5 text-slate-500" />
              <span>Copy</span>
            </button>
          </div>
        </div>

        {/* Search & Filter Controls */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-1">
          {/* Search Box */}
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search transcript text... (/)"
              aria-label="Search transcript"
              className="w-full text-xs pl-9 pr-8 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                aria-label="Clear transcript search"
                title="Clear search"
                className="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-700 text-xs rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Language Filter Pills */}
          <div
            role="group"
            aria-label="Filter by language"
            className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200"
          >
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-600 ml-1.5 mr-1">Lang:</span>
            {['all', ...languagesPresent].map((lang) => (
              <button
                key={lang}
                onClick={() => setSelectedLanguage(lang)}
                aria-pressed={effectiveLanguage === lang}
                aria-label={lang === 'all' ? 'All languages' : getLanguageAriaLabel(lang)}
                title={lang === 'all' ? 'All languages' : getLanguageAriaLabel(lang)}
                className={`flex-1 py-1 text-[11px] font-bold uppercase rounded transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 ${
                  effectiveLanguage === lang
                    ? 'bg-medpark-500 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {lang === 'all' ? 'all' : getLanguageLabel(lang)}
              </button>
            ))}
          </div>

          {/* Speaker Filter Dropdown */}
          <div className="flex items-center space-x-1 bg-white p-1 rounded-lg border border-slate-200">
            <Filter className="w-3.5 h-3.5 text-slate-400 ml-2" aria-hidden="true" />
            <select
              value={selectedSpeaker}
              onChange={(e) => setSelectedSpeaker(e.target.value)}
              aria-label="Filter by speaker"
              className="w-full text-xs bg-transparent border-none text-slate-700 font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 rounded cursor-pointer"
            >
              <option value="all">All Speakers ({speakers.length})</option>
              {speakers.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Utterances List */}
      <p className="sr-only" role="status">
        {filteredSegments.length} of {segments.length} utterances shown
      </p>
      <div
        tabIndex={0}
        role="log"
        aria-label="Transcript utterances"
        className="max-h-[540px] overflow-y-auto divide-y divide-slate-100 p-2 space-y-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-medpark-500/40"
      >
        {filteredSegments.map((seg) => {
          const isActive = activeSegmentId === seg.id;
          const contentText = getSegmentDisplayText(seg);
          const isLowConfidence = typeof seg.confidence === 'number' && seg.confidence < 0.8;

          return (
            <div
              key={seg.id}
              ref={isActive ? activeSegmentRef : null}
              aria-current={isActive ? 'true' : undefined}
              className={`p-3 rounded-xl transition-all ${
                isActive
                  ? 'bg-medpark-50/80 border-2 border-medpark-500/80 shadow-sm'
                  : seg.is_flagged
                  ? 'bg-amber-50/40 border border-amber-200/60'
                  : 'hover:bg-slate-50/80 border border-transparent'
              }`}
            >
              {/* Header: Speaker, Time, Language */}
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center space-x-2">
                  <span
                    className={`font-semibold text-xs px-2 py-0.5 rounded ${
                      isActive ? 'bg-medpark-600 text-white font-bold' : 'text-slate-800 bg-slate-100'
                    }`}
                  >
                    {seg.speaker}
                  </span>

                  <button
                    onClick={() => onSeek(seg.start)}
                    className="inline-flex items-center space-x-1 text-xs font-mono tabular-nums text-medpark-700 hover:text-medpark-900 bg-medpark-50 hover:bg-medpark-100 px-2 py-0.5 rounded-md border border-medpark-500/20 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
                    title="Listen to utterance"
                    aria-label={`Play utterance from ${formatTimestamp(seg.start)}`}
                  >
                    <Play className="w-3 h-3 fill-medpark-600" aria-hidden="true" />
                    <span>
                      {formatTimestamp(seg.start)} - {formatTimestamp(seg.end)}
                    </span>
                  </button>

                  <span
                    className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded border ${getLanguageColor(
                      seg.language
                    )}`}
                    title={getLanguageTitle(seg)}
                  >
                    {getLanguageLabel(seg.language, seg.language_spans)}
                    <span className="sr-only">, {getLanguageAriaLabel(seg.language)}</span>
                  </span>

                  {seg.corrections && seg.corrections.length > 0 && (
                    <span
                      lang="en"
                      className="inline-flex items-center space-x-1 text-[10px] text-sky-700 bg-sky-50 border border-sky-200 px-1.5 py-0.5 rounded font-semibold whitespace-nowrap"
                      title={seg.corrections.map((c) => `${c.was} → ${c.now}`).join('\n')}
                    >
                      <Sparkles className="w-3 h-3 text-sky-600" aria-hidden="true" />
                      <span>corrected</span>
                      <span className="sr-only">
                        by the clinical lexicon: {seg.corrections.map((c) => `${c.was} to ${c.now}`).join('; ')}
                      </span>
                    </span>
                  )}

                  {isLowConfidence && !seg.corrected_text && (
                    <span
                      className="inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded"
                      title={`Recognition confidence ${Math.round(seg.confidence * 100)}% — verify this utterance against the audio`}
                    >
                      <AlertTriangle className="w-3 h-3 text-amber-600" aria-hidden="true" />
                      <span className="font-mono tabular-nums normal-case">
                        {Math.round(seg.confidence * 100)}%
                      </span>
                      <span className="sr-only">recognition confidence, verify against audio</span>
                    </span>
                  )}
                </div>

                {/* Review Flags & Edit Trigger */}
                <div className="flex items-center space-x-2">
                  {seg.is_flagged && (
                    <span
                      className="inline-flex items-center space-x-1 text-[11px] text-amber-800 bg-amber-100/80 border border-amber-300 px-2 py-0.5 rounded-md"
                      title={seg.flag_reason || 'Needs review'}
                    >
                      <AlertTriangle className="w-3 h-3 text-amber-600" />
                      <span>{seg.flag_reason || 'Flagged'}</span>
                    </span>
                  )}

                  {editingId !== seg.id && (
                    <button
                      onClick={() => startEdit(seg)}
                      className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-md transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
                      title="Edit utterance text"
                      aria-label={`Edit utterance at ${formatTimestamp(seg.start)}`}
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>

              {/* Text Body / Inline Editor */}
              {editingId === seg.id ? (
                <div className="mt-2 space-y-2 bg-slate-50 p-2.5 rounded-lg border border-medpark-500/30">
                  <textarea
                    value={editText}
                    lang={seg.language}
                    aria-label={`Corrected text for the utterance at ${formatTimestamp(seg.start)}`}
                    onChange={(e) => setEditText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        saveEdit(seg.id);
                      } else if (e.key === 'Escape') {
                        cancelEdit();
                      }
                    }}
                    className="w-full text-sm p-2 bg-white rounded border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20 font-sans"
                    rows={2}
                    autoFocus
                  />
                  <div className="flex items-center justify-between text-[11px] text-slate-500">
                    <span>Press <kbd className="font-mono bg-white px-1 border rounded">Enter</kbd> to save, <kbd className="font-mono bg-white px-1 border rounded">Esc</kbd> to cancel</span>
                    <div className="flex items-center space-x-2">
                      <button
                        onClick={cancelEdit}
                        disabled={isSaving}
                        className="px-2.5 py-1 text-slate-600 hover:bg-slate-200 rounded transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => saveEdit(seg.id)}
                        disabled={isSaving}
                        className="inline-flex items-center space-x-1 px-3 py-1 bg-medpark-500 text-white font-semibold rounded hover:bg-medpark-600 shadow-sm disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/50 focus-visible:ring-offset-1"
                      >
                        {isSaving ? (
                          <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                        ) : (
                          <Check className="w-3 h-3" aria-hidden="true" />
                        )}
                        <span>{isSaving ? 'Saving...' : 'Save Correction'}</span>
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="pl-1 pt-0.5 space-y-1">
                  <p lang={seg.language} className="text-sm text-slate-800 leading-relaxed">
                    {seg.corrected_text === '' ? (
                      <span className="italic text-slate-400 text-xs">[Utterance removed by reviewer]</span>
                    ) : (
                      renderHighlightedText(contentText, searchQuery)
                    )}
                    {seg.corrected_text !== undefined && seg.corrected_text !== null && (
                      <span
                        lang="en"
                        className="ml-2 text-[10px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded font-semibold uppercase tracking-wider whitespace-nowrap"
                        title={`Human-corrected. Original recognition: ${seg.raw_text}`}
                      >
                        Corrected
                      </span>
                    )}
                  </p>
                  {(seg.raw_text !== contentText || seg.normalized_text) && (
                    <details className="text-[11px] text-slate-500 pt-0.5">
                      <summary className="cursor-pointer hover:text-slate-700 select-none inline-flex items-center space-x-1">
                        <span>Original recognition ({seg.raw_text_origin || 'legacy_unknown'})</span>
                      </summary>
                      <div className="mt-1 pl-2 border-l-2 border-slate-300 font-mono text-[11px] text-slate-600 bg-slate-100/60 p-1.5 rounded">
                        <div><span className="font-semibold text-slate-500">Decoder:</span> {seg.raw_text}</div>
                        {seg.normalized_text && (
                          <div className="text-[10px] text-sky-700 mt-0.5 font-sans">
                            <span className="font-semibold">Normalized ({seg.normalization_version || 'lexicon'}):</span> {seg.normalized_text}
                          </div>
                        )}
                      </div>
                    </details>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {filteredSegments.length === 0 && (
          <div className="text-center py-12 text-sm text-slate-400 space-y-1">
            <p className="font-medium text-slate-500">No matching utterances found.</p>
            <p className="text-xs">Try clearing your search query or adjusting language/speaker filters.</p>
          </div>
        )}
      </div>
    </div>
  );
};
