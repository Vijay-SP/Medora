import React, { useState, useEffect } from 'react';
import { ShieldCheck, Plus, Mail, FileText, Keyboard, Activity, Menu, Cpu, Users } from 'lucide-react';
import { MedoraLogo } from './MedoraLogo';
import { apiClient } from '../api/client';
import { ReadinessResponse } from '../types';

const READINESS_POLL_MS = 60000;

interface NavbarProps {
  onNewMeeting: () => void;
  onOpenDeliveries: () => void;
  onOpenShortcuts: () => void;
  onToggleSidebar?: () => void;
  currentPageTitle?: string;
  meetingsCount: number;
  // People & Voices: shown only when /ready reports voice identification as enabled.
  onOpenPeople?: () => void;
  isPeopleActive?: boolean;
  // Lets the app share the readiness probe instead of polling /ready twice.
  onReadinessChange?: (readiness: ReadinessResponse | null) => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  onNewMeeting,
  onOpenDeliveries,
  onOpenShortcuts,
  onToggleSidebar,
  currentPageTitle = 'Dashboard',
  meetingsCount,
  onOpenPeople,
  isPeopleActive = false,
  onReadinessChange,
}) => {
  const [isOnline, setIsOnline] = useState(true);
  // null = /ready not answered yet (or unreachable); the LLM pill must not claim anything then.
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);

  // Truthful probe: /ready reports the local LLM server/model state, not just process liveness.
  // If it fails, fall back to the cheap /health liveness check so the backend pill stays honest.
  const probeBackend = () => {
    apiClient
      .getReadiness()
      .then((r) => {
        setIsOnline(true);
        setReadiness(r);
        onReadinessChange?.(r);
      })
      .catch(() => {
        setReadiness(null);
        onReadinessChange?.(null);
        fetch('/health')
          .then((res) => setIsOnline(res.ok))
          .catch(() => setIsOnline(false));
      });
  };

  useEffect(() => {
    probeBackend();
    const timer = window.setInterval(probeBackend, READINESS_POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const llm = readiness?.llm_service;
  const llmConnected = Boolean(llm?.connected);
  const llmModelLabel = llm?.model || 'local LLM';
  const backendNotReady = Boolean(readiness && !readiness.ready);
  const voiceIdEnabled = Boolean(readiness?.voice_id?.enabled);

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-20 shadow-xs">
      <div className="w-full px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Left: Mobile Sidebar Toggle + Page Title */}
        <div className="flex items-center space-x-3">
          {onToggleSidebar && (
            <button
              onClick={onToggleSidebar}
              aria-label="Toggle navigation menu"
              className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg sm:hidden transition-colors"
            >
              <Menu className="w-5 h-5" />
            </button>
          )}

          {/* Breadcrumb / Title */}
          <div className="flex items-center space-x-2">
            <span className="text-xs font-bold text-slate-400 uppercase tracking-wider hidden md:inline">
              Medora
            </span>
            <span className="text-slate-300 hidden md:inline">/</span>
            <h1 className="text-sm sm:text-base font-black text-slate-800">
              {currentPageTitle}
            </h1>
          </div>
        </div>

        {/* Center: Badges (Air-gap & System Status) */}
        {/* <div className="hidden lg:flex items-center space-x-3">
          <div className="flex items-center space-x-1.5 px-3 py-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-full text-xs font-semibold">
            <ShieldCheck className="w-4 h-4 text-emerald-600" aria-hidden="true" />
            <span>100% Air-Gapped • Local Only</span>
          </div>

          <div role="status" aria-live="polite" className="flex items-center space-x-2">
            {isOnline ? (
              <span
                className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-bold border ${
                  backendNotReady
                    ? 'bg-amber-50 text-amber-800 border-amber-200'
                    : 'bg-slate-50 text-slate-700 border-slate-200'
                }`}
                title={
                  backendNotReady
                    ? 'Backend is up but /ready reports a missing dependency (LLM, storage)'
                    : 'Local FastAPI backend status'
                }
              >
                <Activity
                  className={`w-3.5 h-3.5 ${backendNotReady ? 'text-amber-500' : 'text-emerald-500'}`}
                  aria-hidden="true"
                />
                <span>{backendNotReady ? 'Backend Not Ready' : 'Backend Ready'}</span>
              </span>
            ) : (
              <button
                onClick={probeBackend}
                className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-bold border bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100 transition-colors"
                title="Retry the local FastAPI backend health probe"
              >
                <Activity className="w-3.5 h-3.5 text-rose-500" aria-hidden="true" />
                <span>Backend disconnected - retry</span>
              </button>
            )}

            {isOnline && !readiness && (
              <button
                onClick={probeBackend}
                className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-bold border bg-amber-50 text-amber-800 border-amber-200 hover:bg-amber-100 transition-colors"
                title="Readiness probe did not answer; LLM state unknown. Click to re-probe."
              >
                <Cpu className="w-3.5 h-3.5 text-amber-500" aria-hidden="true" />
                <span>LLM state unknown</span>
              </button>
            )}
            {isOnline && readiness && llmConnected && (
              <span
                className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-bold border bg-slate-50 text-slate-700 border-slate-200"
                title={`Local LLM via ${llm?.engine || 'ollama'} at ${llm?.endpoint || 'local server'} - ${
                  llm?.loaded ? 'model loaded in VRAM' : 'model available, not loaded'
                }`}
              >
                <Cpu className="w-3.5 h-3.5 text-emerald-500" aria-hidden="true" />
                <span className="font-mono">{llmModelLabel}</span>
                <span className="text-[10px] font-semibold text-slate-500">
                  {llm?.loaded ? 'loaded' : 'connected'}
                </span>
              </span>
            )}
            {isOnline && readiness && !llmConnected && (
              <button
                onClick={probeBackend}
                className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-bold border bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100 transition-colors"
                title={`Local LLM (${llm?.engine || 'ollama'}) is not serving at ${
                  llm?.endpoint || 'the configured endpoint'
                }; new pipelines will fail fast at preflight. Click to re-probe.`}
              >
                <Cpu className="w-3.5 h-3.5 text-rose-500" aria-hidden="true" />
                <span className="font-mono">{llmModelLabel}</span>
                <span>unavailable - retry</span>
              </button>
            )}
          </div>
        </div> */}

        {/* Right: Quick Action Controls */}
        <div className="flex items-center space-x-2">
          <button
            onClick={onOpenShortcuts}
            className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors hidden sm:flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            title="Keyboard Shortcuts (?)"
            aria-label="Keyboard shortcuts"
          >
            <Keyboard className="w-4 h-4" aria-hidden="true" />
          </button>

          {/* {voiceIdEnabled && onOpenPeople && (
            <button
              onClick={onOpenPeople}
              aria-pressed={isPeopleActive}
              className={`inline-flex items-center space-x-1.5 px-3 py-2 border text-xs font-semibold rounded-lg transition-colors shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 ${
                isPeopleActive
                  ? 'bg-medpark-50 text-medpark-700 border-medpark-200'
                  : 'border-slate-200 text-slate-700 hover:bg-slate-50'
              }`}
              title="People & Voices: enrolled voices and consent"
              aria-label="Open People and Voices"
            >
              <Users className={`w-4 h-4 ${isPeopleActive ? 'text-medpark-600' : 'text-slate-500'}`} aria-hidden="true" />
              <span className="hidden sm:inline">People &amp; Voices</span>
            </button>
          )} */}

          {/* <button
            onClick={onOpenDeliveries}
            className="inline-flex items-center space-x-1.5 px-3 py-2 border border-slate-200 text-slate-700 text-xs font-semibold rounded-lg hover:bg-slate-50 transition-colors shadow-xs"
            title="Email Outbox (O)"
            aria-label="Open email outbox"
          >
            <FileText className="w-4 h-4 text-slate-500" aria-hidden="true" />
            <span className="hidden sm:inline">Outbox</span>
          </button> */}

          <button
            onClick={onNewMeeting}
            className="inline-flex items-center space-x-1.5 px-3.5 py-2 bg-medpark-500 text-white text-xs font-bold rounded-lg hover:bg-medpark-600 shadow-xs transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            title="New Meeting (M)"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            <span>New Session</span>
          </button>
        </div>

      </div>
    </header>
  );
};
