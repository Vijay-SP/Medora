import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { DeliveryRecord } from '../types';
import { apiClient } from '../api/client';

const actionStyle = 'px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-300 bg-white hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-medpark-500 disabled:opacity-50';

export const EmailPreview: React.FC<{ record: DeliveryRecord; onSent: () => void }> = ({ record, onSent }) => {
  const [open, setOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<DeliveryRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const current = result || record;

  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    panel?.querySelector<HTMLButtonElement>('button')?.focus();
    const keydown = (event: KeyboardEvent) => {
      // Capture before the drawer's focus trap and the app's global shortcuts.
      event.stopPropagation();
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
      }
      if (event.key === 'Tab' && panel) {
        const controls = Array.from(panel.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], [tabindex="0"]'));
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault(); last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first?.focus();
        }
      }
    };
    document.addEventListener('keydown', keydown, true);
    return () => {
      document.removeEventListener('keydown', keydown, true);
      if (before?.isConnected) before.focus();
    };
  }, [open]);

  const send = async () => {
    if (sending) return;
    setSending(true);
    setError(null);
    try {
      const attempt = await apiClient.sendSavedDelivery(current.id);
      setResult(attempt);
      onSent();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send email. Refresh the outbox before retrying.');
    } finally {
      setSending(false);
    }
  };

  return <>
    <div className="flex flex-wrap items-center gap-2 py-2">
      {(record.languages_included || []).map(language => <span key={language} className="text-[10px] font-bold rounded bg-slate-100 px-2 py-1">{language.toUpperCase()}</span>)}
      {record.body_text != null && <button className={actionStyle} onClick={() => { setError(null); setOpen(true); }}>View Email</button>}
      {record.eml_available && <a className={actionStyle} href={apiClient.getDeliveryEmlUrl(record.id)} download>Download .EML</a>}
    </div>
    {open && createPortal(
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 p-4" onClick={e => { if (e.target === e.currentTarget) setOpen(false); }}>
        <div ref={panelRef} data-email-preview role="dialog" aria-modal="true" aria-label="Email preview"
          className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white p-5 shadow-xl space-y-4">
          <div className="flex justify-between items-center gap-4">
            <h2 className="text-lg font-bold">Email preview · Rev. {current.revision}</h2>
            <button className={actionStyle} onClick={() => setOpen(false)} aria-label="Close email preview">Close</button>
          </div>
          <dl className="text-sm space-y-2 break-words">
            <div><dt className="font-bold inline">Status: </dt><dd className="inline">{current.status === 'saved_locally' ? 'Saved locally — not sent' : current.status}</dd></div>
            <div><dt className="font-bold inline">From: </dt><dd className="inline">{current.from_header || 'Not recorded'}</dd></div>
            <div><dt className="font-bold inline">To: </dt><dd className="inline">{(current.to_recipients?.length ? current.to_recipients : current.recipients).join(', ')}</dd></div>
            {!!current.cc_recipients?.length && <div><dt className="font-bold inline">Cc: </dt><dd className="inline">{current.cc_recipients.join(', ')}</dd></div>}
            <div><dt className="font-bold inline">Subject: </dt><dd className="inline">{current.subject}</dd></div>
            {current.created_at && <div><dt className="font-bold inline">Created: </dt><dd className="inline">{new Date(current.created_at).toLocaleString()}</dd></div>}
          </dl>
          <pre tabIndex={0} className="whitespace-pre-wrap break-words text-sm font-sans leading-relaxed rounded-xl border border-slate-200 bg-slate-50 p-4">{current.body_text}</pre>
          {(error || current.error_message) && <p role="alert" className="text-sm text-rose-700">{error || current.error_message}</p>}
          {current.eml_available && <div className="flex flex-wrap gap-2">
            <a className={actionStyle} href={apiClient.getDeliveryEmlUrl(current.id)} download>Download .EML</a>
            {['saved_locally', 'failed', 'simulated'].includes(current.status) &&
              <button className="px-3 py-1.5 text-xs font-bold rounded-lg bg-medpark-600 hover:bg-medpark-700 text-white shadow-xs focus-visible:ring-2 focus-visible:ring-medpark-500 disabled:opacity-50 transition-colors" disabled={sending} onClick={send}>{sending ? 'Sending…' : 'Resend Email (via SMTP)'}</button>}
          </div>}
          {['saved_locally', 'failed', 'simulated'].includes(current.status) && <p className="text-xs text-slate-500">Resend contacts the configured SMTP relay (127.0.0.1:1025) and sends this approved email to the recipients above.</p>}
        </div>
      </div>, document.body
    )}
  </>;
};
