import React, { useEffect, useRef, useState } from 'react';
import { Keyboard, X, Command } from 'lucide-react';

interface KeyboardShortcutsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const KeyboardShortcutsModal: React.FC<KeyboardShortcutsModalProps> = ({ isOpen, onClose }) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const [hasEntered, setHasEntered] = useState(false);

  // Enter transition built from core Tailwind utilities (no animation plugin is installed):
  // the card is painted once in its "from" state, then transitions in. Under
  // prefers-reduced-motion the motion-safe: from-state never applies, so it just appears.
  useEffect(() => {
    if (!isOpen) {
      setHasEntered(false);
      return;
    }
    const frame = requestAnimationFrame(() => setHasEntered(true));
    return () => cancelAnimationFrame(frame);
  }, [isOpen]);

  // Move focus into the dialog, keep Tab inside it, and hand focus back on close.
  useEffect(() => {
    if (!isOpen) return;
    const panel = panelRef.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const initial = panel?.querySelector<HTMLElement>('[data-autofocus]') || panel;
    initial?.focus();

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !panel) return;
      const focusables = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
        e.preventDefault();
        last.focus();
      }
    };

    document.addEventListener('keydown', handleTab);
    return () => {
      document.removeEventListener('keydown', handleTab);
      previouslyFocused?.focus?.();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const shortcuts = [
    { key: 'Space', description: 'Play / Pause audio playback' },
    { key: '/', description: 'Focus transcript search (Transcript tab only)' },
    { key: 'M', description: 'Open new meeting intake modal' },
    { key: 'O', description: 'Open email outbox drawer' },
    { key: '1', description: 'Switch to Official Minutes (MoM) tab' },
    { key: '2', description: 'Switch to Multilingual Transcript tab' },
    { key: '3', description: 'Switch to Speakers tab (when voice identification is enabled)' },
    { key: '?', description: 'Show / Hide keyboard shortcuts' },
    { key: 'Esc', description: 'Close active modal or drawer' },
  ];

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/50 backdrop-blur-sm p-4 overflow-y-auto"
    >
      {/* items-start + my-auto keeps the card centred when it fits and pinned to the scroll
          origin when it is taller than the viewport, so the header and X stay reachable. */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        tabIndex={-1}
        className={`bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-md my-auto overflow-hidden focus:outline-none transition duration-150 ease-out motion-reduce:transition-none ${
          hasEntered ? 'opacity-100 scale-100' : 'motion-safe:opacity-0 motion-safe:scale-95'
        }`}
      >

        {/* Header */}
        <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-lg bg-medpark-500 text-white flex items-center justify-center">
              <Keyboard className="w-4 h-4" />
            </div>
            <h3 id="shortcuts-title" className="font-bold text-slate-900 text-sm">Keyboard Shortcuts</h3>
          </div>
          <button
            onClick={onClose}
            data-autofocus
            aria-label="Close keyboard shortcuts"
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        {/* Shortcuts List */}
        <dl className="p-4 space-y-2.5 max-h-96 overflow-y-auto divide-y divide-slate-100">
          {shortcuts.map((sc, idx) => (
            <div key={idx} className="flex items-center justify-between text-xs pt-2 first:pt-0">
              <dt className="text-slate-700 font-medium pr-3">{sc.description}</dt>
              <dd>
                <kbd className="px-2 py-1 bg-slate-100 text-slate-800 border border-slate-300 rounded font-mono font-bold shadow-sm">
                  {sc.key}
                </kbd>
              </dd>
            </div>
          ))}
        </dl>

        {/* Footer */}
        <div className="p-3 bg-slate-50 border-t border-slate-200 text-center space-y-1">
          <p className="text-[11px] text-slate-500 flex items-center justify-center space-x-1">
            <Command className="w-3 h-3 text-slate-400" aria-hidden="true" />
            <span>Press <kbd className="font-mono font-semibold px-1 py-0.5 bg-white border border-slate-200 rounded">?</kbd> anytime to toggle this menu</span>
          </p>
          <p className="text-[10px] text-slate-400">
            Shortcuts are paused while you are typing in a field or a dialog is open.
          </p>
        </div>

      </div>
    </div>
  );
};
