import React, { useEffect, useState } from 'react';
import { DeliveryRecord } from '../types';
import { apiClient } from '../api/client';
import { Mail, CheckCircle2, Clock, AlertTriangle, FileDown, X } from 'lucide-react';

interface DeliveryOutboxDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  activeMeetingId?: string;
}

export const DeliveryOutboxDrawer: React.FC<DeliveryOutboxDrawerProps> = ({
  isOpen,
  onClose,
  activeMeetingId,
}) => {
  const [deliveries, setDeliveries] = useState<DeliveryRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadDeliveries();
    }
  }, [isOpen, activeMeetingId]);

  const loadDeliveries = async () => {
    setIsLoading(true);
    try {
      const records = await apiClient.listDeliveries(activeMeetingId);
      setDeliveries(records);
    } catch (err) {
      console.error('Failed to load deliveries:', err);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'dispatched':
        return (
          <span className="inline-flex items-center space-x-1 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full font-medium">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
            <span>Delivered (SMTP)</span>
          </span>
        );
      case 'simulated':
        return (
          <span className="inline-flex items-center space-x-1 text-xs text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full font-medium">
            <Clock className="w-3 h-3 text-blue-600" />
            <span>Simulated (Mailpit Demo)</span>
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center space-x-1 text-xs text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-full font-medium">
            <AlertTriangle className="w-3 h-3 text-rose-600" />
            <span>Delivery Failed</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 text-xs text-slate-700 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-full font-medium">
            <span>Pending</span>
          </span>
        );
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-end bg-slate-900/40 backdrop-blur-xs p-4">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-xl h-[85vh] flex flex-col overflow-hidden animate-in slide-in-from-right duration-200">
        
        {/* Header */}
        <div className="p-5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-lg bg-medpark-500 text-white flex items-center justify-center">
              <Mail className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 text-base">Email Outbox & Routing Log</h3>
              <p className="text-xs text-slate-500">Internal delivery log of official documents</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {isLoading && (
            <div className="text-center py-10 text-xs text-slate-400">Loading delivery records...</div>
          )}

          {!isLoading && deliveries.length === 0 && (
            <div className="text-center py-12 text-sm text-slate-400">
              No messages recorded in outbox.
            </div>
          )}

          {deliveries.map((rec) => (
            <div
              key={rec.id}
              className="p-4 rounded-xl border border-slate-200 bg-white hover:border-medpark-300 transition-colors space-y-2.5"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-900 truncate max-w-xs">
                  {rec.subject}
                </span>
                {getStatusBadge(rec.status)}
              </div>

              {/* Recipients */}
              <div className="text-xs text-slate-600">
                <span className="font-semibold text-slate-700">Recipients ({rec.recipients.length}):</span>{' '}
                <span className="font-mono text-slate-500">{rec.recipients.join(', ')}</span>
              </div>

              {/* Attachments & download buttons */}
              <div className="flex items-center space-x-2 pt-1 border-t border-slate-100">
                <a
                  href={apiClient.getPdfDownloadUrl(rec.meeting_id)}
                  download
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-lg transition-colors"
                >
                  <FileDown className="w-3.5 h-3.5" />
                  <span>Download PDF</span>
                </a>

                <a
                  href={apiClient.getDocxDownloadUrl(rec.meeting_id)}
                  download
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
                >
                  <FileDown className="w-3.5 h-3.5" />
                  <span>Download DOCX</span>
                </a>
              </div>
            </div>
          ))}
        </div>

      </div>
    </div>
  );
};
