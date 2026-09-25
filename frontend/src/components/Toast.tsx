import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from 'lucide-react';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
}

interface ToastContextType {
  showToast: (title: string, message?: string, type?: ToastType) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

// A failure notice must outlive a glance: errors stay until dismissed, warnings linger.
const getToastTtl = (type: ToastType): number | null => {
  if (type === 'error') return null;
  if (type === 'warning') return 10000;
  return 5000;
};

interface ToastItemProps {
  toast: ToastMessage;
  onDismiss: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string, type: ToastType) => void;
}

// Slide-in built from core Tailwind utilities (no animation plugin is installed): the toast is
// painted once in its "from" state, then transitions in. Under prefers-reduced-motion the
// motion-safe: from-state never applies, so the toast just appears.
const ToastItem: React.FC<ToastItemProps> = ({ toast, onDismiss, onPause, onResume }) => {
  const [hasEntered, setHasEntered] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setHasEntered(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div
      role={toast.type === 'error' ? 'alert' : 'status'}
      aria-live={toast.type === 'error' ? 'assertive' : 'polite'}
      aria-atomic="true"
      onMouseEnter={() => onPause(toast.id)}
      onMouseLeave={() => onResume(toast.id, toast.type)}
      onFocus={() => onPause(toast.id)}
      onBlur={() => onResume(toast.id, toast.type)}
      className={`pointer-events-auto p-4 rounded-xl border shadow-lg flex items-start space-x-3 transition-all duration-200 ease-out motion-reduce:transition-none ${
        hasEntered ? 'translate-x-0 opacity-100' : 'motion-safe:translate-x-5 motion-safe:opacity-0'
      } ${
        toast.type === 'success'
          ? 'bg-emerald-900/95 text-white border-emerald-700'
          : toast.type === 'error'
          ? 'bg-rose-900/95 text-white border-rose-700'
          : toast.type === 'warning'
          ? 'bg-amber-900/95 text-white border-amber-700'
          : 'bg-slate-900/95 text-white border-slate-700'
      }`}
    >
      <div className="flex-shrink-0 mt-0.5" aria-hidden="true">
        {toast.type === 'success' && <CheckCircle2 className="w-5 h-5 text-emerald-400" />}
        {toast.type === 'error' && <AlertCircle className="w-5 h-5 text-rose-400" />}
        {toast.type === 'warning' && <AlertTriangle className="w-5 h-5 text-amber-400" />}
        {toast.type === 'info' && <Info className="w-5 h-5 text-blue-400" />}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-bold leading-tight">{toast.title}</p>
        {toast.message && <p className="text-xs text-slate-200 mt-1 leading-snug break-words">{toast.message}</p>}
      </div>

      <button
        onClick={() => onDismiss(toast.id)}
        aria-label={`Dismiss notification: ${toast.title}`}
        className="flex-shrink-0 text-slate-300 hover:text-white p-1.5 -m-1 rounded transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
      >
        <X className="w-4 h-4" aria-hidden="true" />
      </button>
    </div>
  );
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const timersRef = useRef<Map<string, number>>(new Map());

  const removeToast = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Auto-dismiss is paused while the toast is hovered or focused (WCAG 2.2.1).
  const scheduleDismiss = useCallback((id: string, type: ToastType) => {
    const ttl = getToastTtl(type);
    if (ttl === null) return;
    const existing = timersRef.current.get(id);
    if (existing) window.clearTimeout(existing);
    timersRef.current.set(id, window.setTimeout(() => removeToast(id), ttl));
  }, [removeToast]);

  const pauseDismiss = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      timers.clear();
    };
  }, []);

  const showToast = useCallback((title: string, message?: string, type: ToastType = 'success') => {
    const id = Date.now().toString() + Math.random().toString(36).substring(2, 5);
    const newToast: ToastMessage = { id, title, message, type };
    setToasts((prev) => [...prev.slice(-4), newToast]); // keep max 5 visible

    scheduleDismiss(id, type);
  }, [scheduleDismiss]);

  return (
    <ToastContext.Provider value={{ showToast, removeToast }}>
      {children}
      {/* Toast Render Container */}
      <div
        role="region"
        aria-label="Notifications"
        className="fixed top-20 right-4 z-50 flex flex-col space-y-2.5 max-w-sm w-full pointer-events-none"
      >
        {toasts.map((toast) => (
          <ToastItem
            key={toast.id}
            toast={toast}
            onDismiss={removeToast}
            onPause={pauseDismiss}
            onResume={scheduleDismiss}
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};
