import React from 'react';
import { Keyboard, X, Command } from 'lucide-react';

interface KeyboardShortcutsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const KeyboardShortcutsModal: React.FC<KeyboardShortcutsModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  const shortcuts = [
    { key: 'Space', description: 'Play / Pause audio playback' },
    { key: '/', description: 'Focus transcript search input' },
    { key: 'M', description: 'Open new meeting intake modal' },
    { key: 'O', description: 'Open email outbox drawer' },
    { key: '1', description: 'Switch to Official Minutes (MoM) tab' },
    { key: '2', description: 'Switch to Multilingual Transcript tab' },
    { key: '?', description: 'Show / Hide keyboard shortcuts' },
    { key: 'Esc', description: 'Close active modal or drawer' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">

        {/* Header */}
        <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-lg bg-medpark-500 text-white flex items-center justify-center">
              <Keyboard className="w-4 h-4" />
            </div>
            <h3 className="font-bold text-slate-900 text-sm">Keyboard Shortcuts</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Shortcuts List */}
        <div className="p-4 space-y-2.5 max-h-96 overflow-y-auto divide-y divide-slate-100">
          {shortcuts.map((sc, idx) => (
            <div key={idx} className="flex items-center justify-between text-xs pt-2 first:pt-0">
              <span className="text-slate-700 font-medium">{sc.description}</span>
              <kbd className="px-2 py-1 bg-slate-100 text-slate-800 border border-slate-300 rounded font-mono font-bold shadow-2xs">
                {sc.key}
              </kbd>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="p-3 bg-slate-50 border-t border-slate-200 text-center">
          <p className="text-[11px] text-slate-500 flex items-center justify-center space-x-1">
            <Command className="w-3 h-3 text-slate-400" />
            <span>Press <kbd className="font-mono font-semibold px-1 py-0.5 bg-white border border-slate-200 rounded">?</kbd> anytime to toggle this menu</span>
          </p>
        </div>

      </div>
    </div>
  );
};
