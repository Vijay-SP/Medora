import React, { useState, useEffect } from 'react';
import {
  Mail,
  CheckCircle2,
  AlertCircle,
  Clock,
  RefreshCw,
  Search,
  FileDown,
  ShieldCheck,
  Send,
  ExternalLink,
} from 'lucide-react';
import { DeliveryRecord } from '../types';
import { apiClient } from '../api/client';

export const DeliveriesView: React.FC = () => {
  const [deliveries, setDeliveries] = useState<DeliveryRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filterQuery, setFilterQuery] = useState('');
  const [error, setError] = useState<string | null>(null);

  const fetchDeliveries = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiClient.listDeliveries();
      setDeliveries(data);
    } catch (err: any) {
      console.error('Failed to fetch deliveries:', err);
      setError('Could not retrieve email delivery audit log.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchDeliveries();
  }, []);

  const filtered = deliveries.filter((d) => {
    if (!filterQuery.trim()) return true;
    const q = filterQuery.toLowerCase();
    return (
      d.subject.toLowerCase().includes(q) ||
      d.recipients.some((r) => r.toLowerCase().includes(q)) ||
      d.status.toLowerCase().includes(q)
    );
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'dispatched':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-50 text-emerald-800 border border-emerald-200">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
            <span>Dispatched</span>
          </span>
        );
      case 'simulated':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-blue-50 text-blue-800 border border-blue-200">
            <Send className="w-3.5 h-3.5 text-blue-600" />
            <span>Simulated Outbox</span>
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-50 text-rose-800 border border-rose-200">
            <AlertCircle className="w-3.5 h-3.5 text-rose-600" />
            <span>Failed</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-50 text-amber-800 border border-amber-200">
            <Clock className="w-3.5 h-3.5 text-amber-600" />
            <span>Pending</span>
          </span>
        );
    }
  };

  return (
    <div className="w-full space-y-6">
      {/* Header */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center space-x-2 px-3 py-1 bg-blue-50 text-blue-700 border border-blue-200 rounded-full text-xs font-bold mb-2">
            <Mail className="w-3.5 h-3.5 text-blue-600" />
            <span>Hospital SMTP Distribution Log</span>
          </div>
          <h2 className="text-xl font-black text-slate-900">Email Outbox & Governance Audit</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Immutable audit records of all official minutes dispatched to hospital departments and clinicians.
          </p>
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={fetchDeliveries}
            disabled={isLoading}
            className="inline-flex items-center space-x-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-xl transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            placeholder="Search by subject, doctor email, or status..."
            className="w-full text-xs pl-8 pr-4 py-2 rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
          />
        </div>

        <p className="text-xs text-slate-500 font-medium">
          Showing <span className="font-bold text-slate-800">{filtered.length}</span> of {deliveries.length} records
        </p>
      </div>

      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-800 text-xs flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Deliveries List */}
      <div className="space-y-3">
        {filtered.length === 0 ? (
          <div className="bg-white p-12 rounded-2xl border border-slate-200 text-center space-y-2">
            <Mail className="w-10 h-10 text-slate-300 mx-auto" />
            <p className="text-sm font-bold text-slate-700">No email records found</p>
            <p className="text-xs text-slate-400">
              When a clinical reviewer signs off on minutes (or Auto-Pilot is enabled), the delivery audit entries will be recorded here.
            </p>
          </div>
        ) : (
          filtered.map((record) => (
            <div
              key={record.id}
              className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs hover:border-slate-300 transition-all space-y-3"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="space-y-1">
                  <div className="flex items-center space-x-2">
                    {getStatusBadge(record.status)}
                    <span className="text-[11px] font-mono text-slate-400">Rev.{record.revision}</span>
                    <span className="text-[11px] font-mono text-slate-400 truncate" title={record.id}>
                      ID: {record.id.slice(0, 8)}
                    </span>
                  </div>
                  <h3 className="font-bold text-sm text-slate-900">{record.subject || 'Signed Minutes of Meeting'}</h3>
                </div>

                <div className="text-right text-xs text-slate-500">
                  {record.sent_at ? (
                    <span className="font-medium text-slate-700">
                      {new Date(record.sent_at).toLocaleString()}
                    </span>
                  ) : (
                    <span className="italic text-slate-400">Pending transmission</span>
                  )}
                </div>
              </div>

              {/* Recipients list */}
              <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-semibold text-slate-600 mr-1">To:</span>
                {record.recipients?.map((email, idx) => (
                  <span
                    key={idx}
                    className="font-mono text-[11px] px-2 py-0.5 bg-white border border-slate-200 rounded text-slate-700"
                  >
                    {email}
                  </span>
                ))}
              </div>

              {/* Attachments & Artifacts */}
              <div className="flex items-center justify-between pt-1">
                <div className="flex items-center space-x-2 text-xs">
                  {record.pdf_attachment_path && (
                    <a
                      href={apiClient.getDeliveryPdfUrl(record.id)}
                      download
                      className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg font-semibold transition-colors"
                    >
                      <FileDown className="w-3.5 h-3.5 text-rose-600" />
                      <span>Download PDF Attachment</span>
                    </a>
                  )}

                  {record.docx_attachment_path && (
                    <a
                      href={apiClient.getDeliveryDocxUrl(record.id)}
                      download
                      className="inline-flex items-center space-x-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg font-semibold transition-colors"
                    >
                      <FileDown className="w-3.5 h-3.5 text-blue-600" />
                      <span>Download DOCX Attachment</span>
                    </a>
                  )}
                </div>

                {record.smtp_response_code && (
                  <span className="text-[11px] font-mono text-slate-400">
                    SMTP Code: {record.smtp_response_code}
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
