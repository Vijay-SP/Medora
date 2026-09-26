import React, { useEffect, useRef, useState } from 'react';
import { DeliveryRecord, deduplicateDeliveries } from '../types';
import { apiClient } from '../api/client';
import { EmailPreview } from './EmailPreview';
import { Mail, CheckCircle2, Clock, AlertTriangle, FileDown, X, RefreshCw } from 'lucide-react';

interface DeliveryOutboxDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  activeMeetingId?: string;
  onDeliveryChanged?: () => void;
}

export const DeliveryOutboxDrawer: React.FC<DeliveryOutboxDrawerProps> = ({
  isOpen,
  onClose,
  activeMeetingId,
  onDeliveryChanged,
}) => {
  const [deliveries, setDeliveries] = useState<DeliveryRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendingId, setResendingId] = useState<string | null>(null);

  const handleResend = async (deliveryId: string) => {
    if (resendingId) return;
    setResendingId(deliveryId);
    try {
      await apiClient.sendSavedDelivery(deliveryId);
      await loadDeliveries();
      onDeliveryChanged?.();
    } catch (err) {
      console.error('Failed to resend delivery:', err);
      await loadDeliveries();
      onDeliveryChanged?.();
    } finally {
      setResendingId(null);
    }
  };
  const [hasEntered, setHasEntered] = useState(false);

  // Guards against a late response for a previously selected meeting overwriting the list.
  const requestedMeetingIdRef = useRef<string | undefined>(undefined);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      loadDeliveries();
    }
  }, [isOpen, activeMeetingId]);

  // Slide-in built from core Tailwind utilities (no animation plugin is installed): the panel
  // is painted once in its "from" state, then transitions in. Under prefers-reduced-motion the
  // motion-safe: from-state never applies, so the drawer just appears.
  useEffect(() => {
    if (!isOpen) {
      setHasEntered(false);
      return;
    }
    const frame = requestAnimationFrame(() => setHasEntered(true));
    return () => cancelAnimationFrame(frame);
  }, [isOpen]);

  // Move focus into the drawer, keep Tab inside it, and hand focus back on close.
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

  const loadDeliveries = async () => {
    const requestedId = activeMeetingId;
    requestedMeetingIdRef.current = requestedId;
    setIsLoading(true);
    setError(null);
    try {
      const records = await apiClient.listDeliveries(requestedId);
      if (requestedMeetingIdRef.current !== requestedId) return;
      setDeliveries(deduplicateDeliveries(records));
    } catch (err: any) {
      console.error('Failed to load deliveries:', err);
      if (requestedMeetingIdRef.current !== requestedId) return;
      // An audit log must never present a fetch failure as a verified empty outbox.
      setDeliveries([]);
      setError(err?.message || 'Could not load the delivery audit log.');
    } finally {
      if (requestedMeetingIdRef.current === requestedId) {
        setIsLoading(false);
      }
    }
  };

  if (!isOpen) return null;

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'saved_locally':
        return <span className="text-xs font-bold px-2 py-1 rounded-full bg-blue-50 text-blue-800 border border-blue-200">Saved locally · Not sent</span>;
      case 'dispatched':
        return (
          <span className="inline-flex items-center space-x-1 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full font-medium">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" aria-hidden="true" />
            <span>Delivered (SMTP)</span>
          </span>
        );
      case 'simulated':
        return (
          <span className="inline-flex items-center space-x-1 text-xs text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full font-medium">
            <Mail className="w-3 h-3 text-blue-600" aria-hidden="true" />
            <span>Simulated (not sent)</span>
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center space-x-1 text-xs text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-full font-medium">
            <AlertTriangle className="w-3 h-3 text-rose-600" aria-hidden="true" />
            <span>Delivery Failed</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full font-medium">
            <Clock className="w-3 h-3 text-amber-600" aria-hidden="true" />
            <span>Pending</span>
          </span>
        );
    }
  };

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-end bg-slate-900/40 backdrop-blur-sm p-4"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="outbox-title"
        tabIndex={-1}
        className={`bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-xl h-[85vh] flex flex-col overflow-hidden focus:outline-none transition duration-200 ease-out motion-reduce:transition-none ${
          hasEntered ? 'translate-x-0 opacity-100' : 'motion-safe:translate-x-8 motion-safe:opacity-0'
        }`}
      >

        {/* Header */}
        <div className="p-5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-lg bg-medpark-500 text-white flex items-center justify-center">
              <Mail className="w-4 h-4" aria-hidden="true" />
            </div>
            <div>
              <h3 id="outbox-title" className="font-bold text-slate-900 text-base">Email Outbox & Routing Log</h3>
              <p className="text-xs text-slate-500">
                {activeMeetingId ? 'Delivery log for the selected meeting' : 'Internal delivery log of official documents'}
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-1.5">
            <button
              onClick={loadDeliveries}
              disabled={isLoading}
              aria-label="Refresh delivery log"
              title="Refresh delivery log"
              className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
            </button>
            <button
              onClick={onClose}
              data-autofocus
              aria-label="Close email outbox"
              className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              <X className="w-5 h-5" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Content list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3" aria-busy={isLoading}>
          {isLoading && (
            <div role="status" className="text-center py-10 text-xs text-slate-400">Loading delivery records...</div>
          )}

          {!isLoading && error && (
            <div role="alert" className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 space-y-2">
              <div className="flex items-center space-x-2">
                <AlertTriangle className="w-4 h-4 text-rose-600 flex-shrink-0" aria-hidden="true" />
                <span className="text-xs font-bold">Delivery log could not be loaded</span>
              </div>
              <p className="text-xs leading-relaxed">
                {error} The outbox below is <strong>not</strong> a confirmed empty list.
              </p>
              <button
                onClick={loadDeliveries}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-bold bg-white border border-rose-200 rounded-lg text-rose-700 hover:bg-rose-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
              >
                <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Retry</span>
              </button>
            </div>
          )}

          {!isLoading && !error && deliveries.length === 0 && (
            <div className="text-center py-12 px-6 space-y-1">
              <p className="text-sm font-semibold text-slate-500">No messages recorded in outbox.</p>
              <p className="text-xs text-slate-400">
                Minutes appear here once they are signed off and dispatched.
              </p>
            </div>
          )}

          {deliveries.map((rec) => (
            <div
              key={rec.id}
              className="p-4 rounded-xl border border-slate-200 bg-white hover:border-medpark-500 transition-colors space-y-2.5"
            >
              <div className="flex items-start justify-between space-x-3">
                <span className="text-xs font-bold text-slate-900 truncate">
                  {rec.subject}
                </span>
                <span className="flex-shrink-0">{getStatusBadge(rec.status)}</span>
              </div>

              {/* Dispatched revision: the outbox is an audit log of what was actually sent */}
              <div className="flex items-center space-x-2 text-xs text-slate-600">
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200 tabular-nums">
                  Revision {rec.revision}
                </span>
                <span className="font-mono text-slate-500 tabular-nums">
                  {rec.sent_at ? new Date(rec.sent_at).toLocaleString() : 'Not sent yet'}
                </span>
              </div>

              {/* Recipients */}
              <div className="text-xs text-slate-600">
                <span className="font-semibold text-slate-700">Recipients ({rec.recipients.length}):</span>{' '}
                <span className="font-mono text-slate-500 break-all">{rec.recipients.join(', ')}</span>
              </div>

              {/* Failure reason */}
              {rec.error_message && (
                <div className="flex items-start space-x-1.5 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-rose-600 flex-shrink-0 mt-0.5" aria-hidden="true" />
                  <span className="leading-relaxed break-words">
                    <span className="font-bold">Reason: </span>{rec.error_message}
                  </span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2">
                <EmailPreview record={rec} onSent={() => { void loadDeliveries(); onDeliveryChanged?.(); }} />
                {['saved_locally', 'failed', 'simulated'].includes(rec.status) && (
                  <button
                    onClick={() => handleResend(rec.id)}
                    disabled={resendingId === rec.id}
                    className="inline-flex items-center space-x-1 px-2.5 py-1 text-xs font-bold rounded-lg bg-medpark-600 hover:bg-medpark-700 text-white shadow-xs transition-colors disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3 h-3 ${resendingId === rec.id ? 'motion-safe:animate-spin' : ''}`} />
                    <span>{resendingId === rec.id ? 'Sending...' : 'Resend Email'}</span>
                  </button>
                )}
              </div>
              {/* Attachments: delivery-scoped so the exact dispatched revision is served */}
              <div className="flex items-center space-x-2 pt-1 border-t border-slate-100">
                <a
                  href={apiClient.getDeliveryPdfUrl(rec.id)}
                  download
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
                >
                  <FileDown className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>PDF <span className="tabular-nums">(Rev. {rec.revision})</span></span>
                </a>

                <a
                  href={apiClient.getDeliveryDocxUrl(rec.id)}
                  download
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                >
                  <FileDown className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>DOCX <span className="tabular-nums">(Rev. {rec.revision})</span></span>
                </a>
              </div>
            </div>
          ))}
        </div>

      </div>
    </div>
  );
};
