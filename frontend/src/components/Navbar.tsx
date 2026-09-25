import React, { useState, useEffect } from 'react';
import { ShieldCheck, Plus, Mail, FileText, Keyboard, Activity } from 'lucide-react';

interface NavbarProps {
  onNewMeeting: () => void;
  onOpenDeliveries: () => void;
  onOpenShortcuts: () => void;
  meetingsCount: number;
}

export const Navbar: React.FC<NavbarProps> = ({
  onNewMeeting,
  onOpenDeliveries,
  onOpenShortcuts,
  meetingsCount,
}) => {
  const [isOnline, setIsOnline] = useState(true);

  useEffect(() => {
    // Quick health probe
    fetch('/health')
      .then((res) => setIsOnline(res.ok))
      .catch(() => setIsOnline(false));
  }, []);

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-2xs">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Brand */}
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-medpark-500 flex items-center justify-center text-white font-black text-xl shadow-md tracking-wider">
            M
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-lg text-slate-900 tracking-tight">MEDPARK</span>
              <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-medpark-50 text-medpark-700 border border-medpark-200">
                Meeting Intelligence
              </span>
            </div>
            <p className="text-[11px] text-slate-500 font-medium">Medpark International Hospital • Chișinău</p>
          </div>
        </div>

        {/* Security, Server Status & Badges */}
        <div className="hidden lg:flex items-center space-x-3">
          <div className="flex items-center space-x-1.5 px-3 py-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-full text-xs font-semibold">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span>100% Air-Gapped • Zero Cloud Data</span>
          </div>

          <div className="flex items-center space-x-1.5 px-3 py-1 bg-blue-50 text-blue-800 border border-blue-200 rounded-full text-xs font-semibold">
            <Mail className="w-3.5 h-3.5 text-blue-600" />
            <span>Local Mailpit</span>
          </div>

          <div
            className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-bold border ${
              isOnline
                ? 'bg-slate-50 text-slate-700 border-slate-200'
                : 'bg-rose-50 text-rose-700 border-rose-200'
            }`}
            title="Local FastAPI Backend Status"
          >
            <Activity className={`w-3.5 h-3.5 ${isOnline ? 'text-emerald-500 animate-pulse' : 'text-rose-500'}`} />
            <span>{isOnline ? 'System Ready' : 'Backend Disconnected'}</span>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center space-x-2.5">
          <button
            onClick={onOpenShortcuts}
            className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors hidden sm:flex items-center justify-center"
            title="Keyboard Shortcuts (?)"
          >
            <Keyboard className="w-4 h-4" />
          </button>

          <button
            onClick={onOpenDeliveries}
            className="inline-flex items-center space-x-2 px-3 py-2 border border-slate-200 text-slate-700 text-xs font-semibold rounded-lg hover:bg-slate-50 transition-colors shadow-2xs"
          >
            <FileText className="w-4 h-4 text-slate-500" />
            <span className="hidden sm:inline">Email Outbox</span>
          </button>

          <button
            onClick={onNewMeeting}
            className="inline-flex items-center space-x-1.5 px-4 py-2 bg-medpark-500 text-white text-xs font-bold rounded-lg hover:bg-medpark-600 shadow-sm transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>New Meeting</span>
          </button>
        </div>

      </div>
    </header>
  );
};
