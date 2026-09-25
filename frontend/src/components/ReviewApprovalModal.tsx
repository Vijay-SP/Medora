import React, { useState, useEffect, useRef } from 'react';
import { Meeting } from '../types';
import { CheckCircle2, ShieldCheck, Mail, X, Loader2, FileText } from 'lucide-react';

interface ReviewApprovalModalProps {
  meeting: Meeting;
  isOpen: boolean;
  onClose: () => void;
  onApprove: (reviewerName: string, reviewerRole: string, comments: string) => Promise<void>;
}

export const ReviewApprovalModal: React.FC<ReviewApprovalModalProps> = ({
  meeting,
  isOpen,
  onClose,
  onApprove,
}) => {
  // A legally meaningful signature is never pre-filled: the signatory types their own name.
  const [reviewerName, setReviewerName] = useState('');
  const [reviewerRole, setReviewerRole] = useState('');
  const [comments, setComments] = useState('');
  const [hasVerifiedEvidence, setHasVerifiedEvidence] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasEntered, setHasEntered] = useState(false);

  const panelRef = useRef<HTMLDivElement>(null);

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

  const isDirty = Boolean(reviewerName.trim() || reviewerRole.trim() || comments.trim());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reviewerName.trim() || !reviewerRole.trim()) {
      setFormError('Your full name and clinical role are required before signing.');
      return;
    }
    if (!hasVerifiedEvidence) {
      setFormError('Confirm that you reviewed the minutes before signing.');
      return;
    }
    setFormError(null);

    setIsSubmitting(true);
    try {
      await onApprove(reviewerName, reviewerRole, comments);
      onClose();
    } catch (err) {
      console.error('Approval failed:', err);
      setFormError('The sign-off could not be recorded. Check the notification for details and try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // A stray backdrop click must never silently discard a partly typed sign-off.
  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || isDirty) return;
    onClose();
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
        aria-labelledby="approve-title"
        tabIndex={-1}
        className={`bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-lg my-auto overflow-hidden focus:outline-none transition duration-150 ease-out motion-reduce:transition-none ${
          hasEntered ? 'opacity-100 scale-100' : 'motion-safe:opacity-0 motion-safe:scale-95'
        }`}
      >

        {/* Modal Header */}
        <div className="p-5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center">
              <CheckCircle2 className="w-5 h-5" aria-hidden="true" />
            </div>
            <div>
              <h3 id="approve-title" className="font-bold text-slate-900 text-base">Clinical Review & Formal Sign-Off</h3>
              <p className="text-xs text-slate-500">Official sign-off and email distribution trigger</p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close sign-off dialog"
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* What exactly is being signed */}
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-1.5 text-xs">
            <div className="flex items-start space-x-2">
              <FileText className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
              <span className="font-bold text-slate-900 text-sm leading-snug">{meeting.title}</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-slate-600 pl-6">
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-white text-slate-600 border border-slate-200 tabular-nums">
                Revision {meeting.current_revision}
              </span>
              <span className="tabular-nums">{meeting.attendees.length} participants</span>
              <span className="text-slate-300" aria-hidden="true">•</span>
              <span className="capitalize">{meeting.meeting_type} routing</span>
            </div>
          </div>

          <div className="bg-blue-50/70 border border-blue-200 rounded-xl p-3.5 space-y-1.5">
            <div className="flex items-center space-x-2 text-xs font-semibold text-blue-900">
              <Mail className="w-4 h-4 text-blue-600" aria-hidden="true" />
              <span>Delivery Policy: {meeting.meeting_type.toUpperCase()}</span>
            </div>
            <p className="text-xs text-blue-700 leading-relaxed">
              Upon signing, the official minutes (PDF + DOCX) will be automatically dispatched via the secure local SMTP server to:
            </p>
            <p className="text-xs font-semibold text-blue-900 tabular-nums">{meeting.attendees.length} recipients</p>
            <ul className="text-[11px] font-mono text-blue-800 space-y-0.5 max-h-20 overflow-y-auto">
              {meeting.attendees.map((a) => (
                <li key={a.id} className="break-all">{a.email}</li>
              ))}
            </ul>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="approve-name" className="text-xs font-semibold text-slate-700">
              Reviewer Full Name / Signatory <span className="text-rose-600" aria-hidden="true">*</span>
            </label>
            <input
              id="approve-name"
              type="text"
              required
              aria-required="true"
              data-autofocus
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              placeholder="e.g., Dr. Elena Ceban"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="approve-role" className="text-xs font-semibold text-slate-700">
              Clinical Role / Designation <span className="text-rose-600" aria-hidden="true">*</span>
            </label>
            <input
              id="approve-role"
              type="text"
              required
              aria-required="true"
              value={reviewerRole}
              onChange={(e) => setReviewerRole(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              placeholder="e.g., Medical Director"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="approve-comments" className="text-xs font-semibold text-slate-700">Review Comments & Notes (Optional)</label>
            <textarea
              id="approve-comments"
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              rows={2}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              placeholder="e.g., Decisions verified with department chief..."
            />
          </div>

          {/* Explicit confirmation gate before an irreversible dispatch */}
          <label htmlFor="approve-confirm" className="flex items-start space-x-2.5 text-xs text-slate-700 leading-relaxed cursor-pointer">
            <input
              id="approve-confirm"
              type="checkbox"
              checked={hasVerifiedEvidence}
              onChange={(e) => setHasVerifiedEvidence(e.target.checked)}
              className="accent-emerald-600 w-4 h-4 mt-px flex-shrink-0"
            />
            <span>I have listened to the audio evidence for each decision and action item.</span>
          </label>

          {formError && (
            <p role="alert" className="text-[11px] font-semibold text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2">
              {formError}
            </p>
          )}

          {/* Footer Buttons */}
          <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-100">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 font-medium rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !hasVerifiedEvidence}
              aria-busy={isSubmitting}
              className="inline-flex items-center space-x-2 px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm rounded-lg shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 motion-safe:animate-spin" aria-hidden="true" />
                  <span>Dispatching...</span>
                </>
              ) : (
                <>
                  <ShieldCheck className="w-4 h-4" aria-hidden="true" />
                  <span>Sign & Dispatch Email</span>
                </>
              )}
            </button>
          </div>
        </form>

      </div>
    </div>
  );
};
