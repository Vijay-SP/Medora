import React from 'react';
import { ShieldCheck, Plus, Sparkles, Mail, FileText } from 'lucide-react';

interface NavbarProps {
  onNewMeeting: () => void;
  onOpenDeliveries: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onNewMeeting, onOpenDeliveries }) => {
  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Brand */}
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-lg bg-medpark-500 flex items-center justify-center text-white font-bold text-xl shadow-md">
            M
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-lg text-slate-900 tracking-tight">MEDPARK</span>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-medpark-50 text-medpark-700 border border-medpark-100">
                Meeting Intelligence
              </span>
            </div>
            <p className="text-xs text-slate-500">Medpark International Hospital • Chișinău</p>
          </div>
        </div>

        {/* Security & Offline Badge */}
        <div className="hidden md:flex items-center space-x-3">
          <div className="flex items-center space-x-1.5 px-3 py-1 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full text-xs font-medium">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span>100% Offline • Zero Cloud Data</span>
          </div>

          <div className="flex items-center space-x-1.5 px-3 py-1 bg-blue-50 text-blue-700 border border-blue-200 rounded-full text-xs font-medium">
            <Mail className="w-3.5 h-3.5 text-blue-600" />
            <span>Local Mailpit :1025</span>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center space-x-3">
          <button
            onClick={onOpenDeliveries}
            className="inline-flex items-center space-x-2 px-3 py-2 border border-slate-200 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 transition-colors"
          >
            <FileText className="w-4 h-4 text-slate-500" />
            <span>Email Outbox</span>
          </button>

          <button
            onClick={onNewMeeting}
            className="inline-flex items-center space-x-2 px-4 py-2 bg-medpark-500 text-white text-sm font-semibold rounded-lg hover:bg-medpark-600 shadow-sm transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>New Meeting</span>
          </button>
        </div>

      </div>
    </header>
  );
};
