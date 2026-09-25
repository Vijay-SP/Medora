import React, { useState } from 'react';
import { Meeting } from '../types';
import { CheckCircle2, ShieldCheck, Mail, X, Loader2 } from 'lucide-react';

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
  const [reviewerName, setReviewerName] = useState('Dr. Elena Ceban');
  const [reviewerRole, setReviewerRole] = useState('Medical Director / Clinical Reviewer');
  const [comments, setComments] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reviewerName.trim()) return;

    setIsSubmitting(true);
    try {
      await onApprove(reviewerName, reviewerRole, comments);
      onClose();
    } catch (err) {
      console.error('Approval failed:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
      <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-lg overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        
        {/* Modal Header */}
        <div className="p-5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center">
              <CheckCircle2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 text-base">Clinical Review & Formal Sign-Off</h3>
              <p className="text-xs text-slate-500">Official sign-off and email distribution trigger</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div className="bg-blue-50/70 border border-blue-200 rounded-xl p-3.5 space-y-1.5">
            <div className="flex items-center space-x-2 text-xs font-semibold text-blue-900">
              <Mail className="w-4 h-4 text-blue-600" />
              <span>Delivery Policy: {meeting.meeting_type.toUpperCase()}</span>
            </div>
            <p className="text-xs text-blue-700 leading-relaxed">
              Upon signing, the official minutes (PDF + DOCX) will be automatically dispatched to the internal hospital distribution list via the secure local SMTP server.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700">Reviewer Full Name / Signatory</label>
            <input
              type="text"
              required
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              placeholder="e.g., Dr. Elena Ceban"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700">Clinical Role / Designation</label>
            <input
              type="text"
              required
              value={reviewerRole}
              onChange={(e) => setReviewerRole(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              placeholder="e.g., Medical Director"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700">Review Comments & Notes (Optional)</label>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              rows={2}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              placeholder="e.g., Decisions verified with department chief..."
            />
          </div>

          {/* Footer Buttons */}
          <div className="flex items-center justify-end space-x-3 pt-3 border-t border-slate-100">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 font-medium rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center space-x-2 px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm rounded-lg shadow-sm transition-all disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Dispatching...</span>
                </>
              ) : (
                <>
                  <ShieldCheck className="w-4 h-4" />
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
