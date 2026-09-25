import React, { useState, useEffect, useRef } from 'react';
import { TranscriptSegment } from '../types';
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

  // Collect unique speakers
  const speakers = Array.from(new Set(segments.map((s) => s.speaker)));

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

  // Filter segments
  const filteredSegments = segments.filter((seg) => {
    // Language filter
    if (selectedLanguage !== 'all' && seg.language.toLowerCase() !== selectedLanguage.toLowerCase()) {
      return false;
    }
    // Speaker filter
    if (selectedSpeaker !== 'all' && seg.speaker !== selectedSpeaker) {
      return false;
    }
    // Search query filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const text = (seg.display_text || seg.corrected_text || seg.raw_text).toLowerCase();
      const speaker = seg.speaker.toLowerCase();
      return text.includes(q) || speaker.includes(q);
    }
    return true;
  });

  const startEdit = (seg: TranscriptSegment) => {
    setEditingId(seg.id);
    setEditText(seg.display_text || seg.corrected_text || seg.raw_text);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditText('');
  };

  const saveEdit = async (segId: string) => {
    if (!editText.trim()) return;
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
          `[${formatTimestamp(s.start)} - ${formatTimestamp(s.end)}] ${s.speaker} (${s.language.toUpperCase()}): ${
            s.display_text || s.corrected_text || s.raw_text
          }`
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

  const getLanguageColor = (lang: string) => {
    switch (lang.toLowerCase()) {
      case 'ro':
        return 'bg-blue-50 text-blue-700 border-blue-200';
      case 'ru':
        return 'bg-amber-50 text-amber-700 border-amber-200';
      case 'en':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
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
            {['all', 'ro', 'ru', 'en'].map((lang) => (
              <button
                key={lang}
                onClick={() => setSelectedLanguage(lang)}
                aria-pressed={selectedLanguage === lang}
                aria-label={lang === 'all' ? 'All languages' : lang.toUpperCase()}
                className={`flex-1 py-1 text-[11px] font-bold uppercase rounded transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 ${
                  selectedLanguage === lang
                    ? 'bg-medpark-500 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {lang}
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
          const contentText = seg.display_text || seg.corrected_text || seg.raw_text;
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
                  >
                    {seg.language}
                  </span>

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
                        disabled={isSaving || !editText.trim()}
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
                <p lang={seg.language} className="text-sm text-slate-800 leading-relaxed pl-1 pt-0.5">
                  {renderHighlightedText(contentText, searchQuery)}
                  {seg.corrected_text && (
                    <span
                      lang="en"
                      className="ml-2 text-[10px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded font-semibold uppercase tracking-wider whitespace-nowrap"
                      title={`Human-corrected. Original recognition: ${seg.raw_text}`}
                    >
                      Corrected
                    </span>
                  )}
                </p>
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
