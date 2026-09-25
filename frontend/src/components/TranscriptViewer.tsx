import React, { useState } from 'react';
import { TranscriptSegment } from '../types';
import { Play, Edit2, Check, X, AlertTriangle } from 'lucide-react';

interface TranscriptViewerProps {
  segments: TranscriptSegment[];
  onSeek: (seconds: number) => void;
  onUpdateSegment: (segmentId: string, correctedText: string) => Promise<void>;
}

export const TranscriptViewer: React.FC<TranscriptViewerProps> = ({
  segments,
  onSeek,
  onUpdateSegment,
}) => {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const startEdit = (seg: TranscriptSegment) => {
    setEditingId(seg.id);
    setEditText(seg.display_text);
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
    } catch (err) {
      console.error('Failed to save correction:', err);
    } finally {
      setIsSaving(false);
    }
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

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm divide-y divide-slate-100 overflow-hidden">
      <div className="p-4 bg-slate-50/70 border-b border-slate-200 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-slate-900 text-sm">Synchronized Multilingual Transcript</h3>
          <p className="text-xs text-slate-500">
            Click on timestamp to listen to the corresponding audio segment.
          </p>
        </div>
        <span className="text-xs font-medium text-slate-500 bg-white px-2.5 py-1 rounded-md border border-slate-200">
          {segments.length} utterances
        </span>
      </div>

      <div className="max-h-[520px] overflow-y-auto divide-y divide-slate-100 p-2 space-y-1">
        {segments.map((seg) => (
          <div
            key={seg.id}
            className={`p-3 rounded-lg transition-colors hover:bg-slate-50/80 ${
              seg.is_flagged ? 'bg-amber-50/40 border border-amber-200/60' : ''
            }`}
          >
            {/* Header: Speaker, Time, Badges */}
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center space-x-2">
                <span className="font-semibold text-xs text-slate-800 bg-slate-100 px-2 py-0.5 rounded">
                  {seg.speaker}
                </span>

                <button
                  onClick={() => onSeek(seg.start)}
                  className="inline-flex items-center space-x-1 text-xs font-mono text-medpark-600 hover:text-medpark-800 bg-medpark-50 hover:bg-medpark-100 px-1.5 py-0.5 rounded transition-colors"
                  title="Listen to segment"
                >
                  <Play className="w-3 h-3 fill-medpark-600" />
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
              </div>

              {/* Review Flags & Edit Button */}
              <div className="flex items-center space-x-2">
                {seg.is_flagged && (
                  <span
                    className="inline-flex items-center space-x-1 text-[11px] text-amber-800 bg-amber-100/70 px-2 py-0.5 rounded"
                    title={seg.flag_reason || 'Needs review'}
                  >
                    <AlertTriangle className="w-3 h-3 text-amber-600" />
                    <span>{seg.flag_reason || 'Flagged'}</span>
                  </span>
                )}

                {editingId !== seg.id && (
                  <button
                    onClick={() => startEdit(seg)}
                    className="p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded transition-colors"
                    title="Edit transcript text"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>

            {/* Utterance Text / Editor */}
            {editingId === seg.id ? (
              <div className="mt-2 space-y-2">
                <textarea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  className="w-full text-sm p-2 rounded border border-medpark-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  rows={2}
                />
                <div className="flex items-center space-x-2 justify-end">
                  <button
                    onClick={cancelEdit}
                    disabled={isSaving}
                    className="px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-100 rounded"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => saveEdit(seg.id)}
                    disabled={isSaving}
                    className="inline-flex items-center space-x-1 px-3 py-1 bg-medpark-500 text-white text-xs font-semibold rounded hover:bg-medpark-600 shadow-sm"
                  >
                    <Check className="w-3 h-3" />
                    <span>Save</span>
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-800 leading-relaxed pl-1">
                {seg.display_text || seg.corrected_text || seg.raw_text}
                {seg.corrected_text && (
                  <span className="ml-2 text-[10px] text-emerald-600 font-semibold uppercase tracking-wider">
                    (Edited)
                  </span>
                )}
              </p>
            )}
          </div>
        ))}

        {segments.length === 0 && (
          <div className="text-center py-10 text-sm text-slate-400">
            No utterances available yet.
          </div>
        )}
      </div>
    </div>
  );
};
