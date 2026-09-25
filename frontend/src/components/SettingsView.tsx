import React from 'react';
import {
  ShieldCheck,
  Cpu,
  HardDrive,
  Mail,
  Keyboard,
  Info,
  ExternalLink,
  CheckCircle2,
  Server,
  Sparkles,
} from 'lucide-react';
import { MedoraLogo } from './MedoraLogo';

export const SettingsView: React.FC = () => {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center space-x-2 px-3 py-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-full text-xs font-bold mb-2">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
            <span>Air-Gapped Hospital Intelligence</span>
          </div>
          <h2 className="text-xl font-black text-slate-900">System Diagnostics & Environment</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Medora operates 100% offline with zero outbound cloud connections for patient data privacy.
          </p>
        </div>

        <MedoraLogo size="sm" showTagline={false} />
      </div>

      {/* Grid: Diagnostics */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Card 1: Offline Speech & Diarization */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs space-y-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center flex-shrink-0">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-sm text-slate-900">Speech & Diarization Engine</h3>
              <p className="text-[11px] text-slate-500">Local Neural Audio Pipeline</p>
            </div>
          </div>

          <div className="divide-y divide-slate-100 text-xs">
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500">ASR Architecture</span>
              <span className="font-mono font-semibold text-slate-800">Faster-Whisper (Large-v3 / Small)</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500">Compute Backend</span>
              <span className="inline-flex items-center space-x-1 font-mono font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">
                <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                <span>CUDA (GPU Acceleration)</span>
              </span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500">Speaker Clustering</span>
              <span className="font-mono font-semibold text-slate-800">PyAnnote 3.1 Biometric Vectors</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500">Languages Supported</span>
              <span className="font-semibold text-slate-800">Romanian, Russian, English (Mixed)</span>
            </div>
          </div>
        </div>

        {/* Card 2: Clinical Extraction & Minutes */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs space-y-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center flex-shrink-0">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-sm text-slate-900">Clinical Extraction & LLM</h3>
              <p className="text-[11px] text-slate-500">Evidence Grounding & Decisions</p>
            </div>
          </div>

          <div className="divide-y divide-slate-100 text-xs">
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500">Extraction Model</span>
              <span className="font-mono font-semibold text-slate-800">Qwen-2.5-7B-Instruct (GGUF / Local)</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500">Fallback Semantic Engine</span>
              <span className="font-semibold text-emerald-700">Regex & Grammar Grounding Active</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500">Document Generators</span>
              <span className="font-mono font-semibold text-slate-800">FPDF2 (PDF) & Python-docx (DOCX)</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500">Clinical Gate</span>
              <span className="font-semibold text-slate-800">Human Sign-off Mandatory in Supervised</span>
            </div>
          </div>
        </div>

        {/* Card 3: Storage & Air-Gap Security */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs space-y-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center flex-shrink-0">
              <HardDrive className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-sm text-slate-900">Storage & Privacy Vault</h3>
              <p className="text-[11px] text-slate-500">On-Premises Local Filesystem</p>
            </div>
          </div>

          <div className="divide-y divide-slate-100 text-xs font-mono">
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500 font-sans">Database Engine</span>
              <span className="font-semibold text-slate-800">JSON File Repository (Atomic RLock)</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500 font-sans">Storage Directory</span>
              <span className="text-slate-700 text-[11px]">data/store/</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500 font-sans">Uploads Vault</span>
              <span className="text-slate-700 text-[11px]">data/uploads/</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500 font-sans">Network Egress</span>
              <span className="text-emerald-700 font-sans font-bold">Blocked (Air-Gapped)</span>
            </div>
          </div>
        </div>

        {/* Card 4: Local SMTP Mailpit */}
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs space-y-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center flex-shrink-0">
              <Mail className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-sm text-slate-900">Hospital SMTP Dispatch</h3>
              <p className="text-[11px] text-slate-500">Local Safe Mailpit Outbox</p>
            </div>
          </div>

          <div className="divide-y divide-slate-100 text-xs font-mono">
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500 font-sans">SMTP Host</span>
              <span className="text-slate-800">127.0.0.1:1025</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500 font-sans">Mailpit Web UI</span>
              <a
                href="http://127.0.0.1:8025"
                target="_blank"
                rel="noreferrer"
                className="text-blue-600 hover:underline flex items-center space-x-1"
              >
                <span>http://127.0.0.1:8025</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500 font-sans">Simulated Delivery</span>
              <span className="text-slate-800 font-sans font-semibold">Enabled if SMTP Unreachable</span>
            </div>
            <div className="py-2 flex justify-between items-center">
              <span className="text-slate-500 font-sans">Audit Idempotency</span>
              <span className="text-slate-800">UUID v4 Tokenized</span>
            </div>
          </div>
        </div>
      </div>

      {/* Keyboard Shortcuts Reference */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs space-y-4">
        <div className="flex items-center space-x-2">
          <Keyboard className="w-4 h-4 text-slate-600" />
          <h3 className="font-bold text-sm text-slate-900">Power Reviewer Keyboard Shortcuts</h3>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-xs">
          <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center justify-between">
            <span className="text-slate-600">Play / Pause Audio</span>
            <kbd className="px-2 py-1 bg-white border border-slate-300 rounded font-mono font-bold text-slate-800 shadow-xs">
              Space
            </kbd>
          </div>
          <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center justify-between">
            <span className="text-slate-600">Start / New Meeting</span>
            <kbd className="px-2 py-1 bg-white border border-slate-300 rounded font-mono font-bold text-slate-800 shadow-xs">
              M
            </kbd>
          </div>
          <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center justify-between">
            <span className="text-slate-600">Open Email Outbox</span>
            <kbd className="px-2 py-1 bg-white border border-slate-300 rounded font-mono font-bold text-slate-800 shadow-xs">
              O
            </kbd>
          </div>
          <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center justify-between">
            <span className="text-slate-600">Switch to Minutes Tab</span>
            <kbd className="px-2 py-1 bg-white border border-slate-300 rounded font-mono font-bold text-slate-800 shadow-xs">
              1
            </kbd>
          </div>
          <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center justify-between">
            <span className="text-slate-600">Switch to Transcript Tab</span>
            <kbd className="px-2 py-1 bg-white border border-slate-300 rounded font-mono font-bold text-slate-800 shadow-xs">
              2
            </kbd>
          </div>
          <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center justify-between">
            <span className="text-slate-600">Dismiss / Close Modals</span>
            <kbd className="px-2 py-1 bg-white border border-slate-300 rounded font-mono font-bold text-slate-800 shadow-xs">
              Esc
            </kbd>
          </div>
        </div>
      </div>
    </div>
  );
};
