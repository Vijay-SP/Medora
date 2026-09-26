import React, { useEffect, useRef, useState } from 'react';
import {
  X,
  Mic,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
  Info,
} from 'lucide-react';
import { VoiceProfile, SampleQuality } from '../../types';
import { apiClient } from '../../api/client';
import { AudioRecorder } from '../AudioRecorder';
import { ConsentNotice, CONSENT_STATEMENT_VERSION } from './ConsentNotice';
import { formatSpeechSeconds } from './VoiceProfileCard';

interface EnrollmentDrawerProps {
  profile: VoiceProfile | null;
  isOpen: boolean;
  onClose: () => void;
  // Called with the refreshed summary after consent or after every stored sample.
  onProfileChange: (profile: VoiceProfile) => void;
}

// Fixed reading passages (~20 s each at a natural meeting pace). The same text for everyone, so
// enrollment quality depends on the voice and the room, not on what was said. Read one passage per
// sample, in the usual seat, through the room microphone: matched-condition enrollment is what
// makes the voiceprint useful on real far-field meeting audio.
const ENROLLMENT_PROMPTS: { lang: 'ro' | 'ru' | 'en'; label: string; text: string }[] = [
  {
    lang: 'ro',
    label: 'Română',
    text:
      'Bună ziua, colegi. Astăzi discutăm planul de tratament pentru pacienții internați săptămâna ' +
      'aceasta. Propun să revizuim dozele de anticoagulant și să programăm consultul cardiologic ' +
      'pentru joi dimineață. Dacă apar modificări, vă rog să le notați în foaia de observație și să ' +
      'anunțați asistenta de tură. Mulțumesc, trecem la următorul punct de pe ordinea de zi.',
  },
  {
    lang: 'ru',
    label: 'Русский',
    text:
      'Добрый день, коллеги. Сегодня мы обсуждаем план лечения пациентов, поступивших на этой ' +
      'неделе. Предлагаю пересмотреть дозировку антикоагулянтов и назначить консультацию кардиолога ' +
      'на четверг утром. Если появятся изменения, пожалуйста, внесите их в историю болезни и ' +
      'сообщите дежурной медсестре. Спасибо, переходим к следующему вопросу повестки.',
  },
  {
    lang: 'en',
    label: 'English',
    text:
      'Good morning, everyone. Today we are reviewing the treatment plan for the patients admitted ' +
      'this week. I suggest we revisit the anticoagulant doses and schedule the cardiology consult ' +
      'for Thursday morning. If anything changes, please note it in the patient record and let the ' +
      'nurse on duty know. Thank you, let us move on to the next item on the agenda.',
  },
];

const VERDICT_META: Record<
  SampleQuality['verdict'],
  { label: string; className: string; Icon: React.FC<{ className?: string }> }
> = {
  good: { label: 'Good - stored', className: 'bg-emerald-50 text-emerald-800 border-emerald-200', Icon: CheckCircle2 },
  usable: { label: 'Usable - stored', className: 'bg-amber-50 text-amber-900 border-amber-300', Icon: AlertTriangle },
  reject: { label: 'Rejected - nothing stored', className: 'bg-rose-50 text-rose-800 border-rose-200', Icon: XCircle },
};

interface SampleResult {
  id: string;
  at: Date;
  quality: SampleQuality;
}

// Renders a SampleQuality VERBATIM: the numbers and reasons are the backend's verdict, not a UI
// interpretation of it.
const SampleQualityCard: React.FC<{ result: SampleResult }> = ({ result }) => {
  const q = result.quality;
  const meta = VERDICT_META[q.verdict] ?? VERDICT_META.reject;
  const VerdictIcon = meta.Icon;
  return (
    <li className={`rounded-xl border p-3 space-y-2 ${meta.className}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center space-x-1.5 text-xs font-bold">
          <VerdictIcon className="w-4 h-4" />
          <span>{meta.label}</span>
        </span>
        <span className="text-[10px] font-mono tabular-nums opacity-80">{result.at.toLocaleTimeString()}</span>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-1 text-[11px] tabular-nums">
        <div>
          <dt className="font-bold uppercase tracking-wider opacity-70 text-[9px]">Duration</dt>
          <dd className="font-mono">{q.duration_seconds.toFixed(1)} s</dd>
        </div>
        <div>
          <dt className="font-bold uppercase tracking-wider opacity-70 text-[9px]">Speech</dt>
          <dd className="font-mono">{q.speech_seconds.toFixed(1)} s</dd>
        </div>
        <div>
          <dt className="font-bold uppercase tracking-wider opacity-70 text-[9px]">Level</dt>
          <dd className="font-mono">{q.mean_dbfs.toFixed(1)} dBFS</dd>
        </div>
        <div>
          <dt className="font-bold uppercase tracking-wider opacity-70 text-[9px]">Clipped</dt>
          <dd className="font-mono">{(q.clipped_fraction * 100).toFixed(2)} %</dd>
        </div>
      </dl>
      {q.reasons.length > 0 && (
        <ul className="list-disc list-inside text-xs leading-relaxed space-y-0.5">
          {q.reasons.map((r, idx) => (
            <li key={idx}>{r}</li>
          ))}
        </ul>
      )}
    </li>
  );
};

export const EnrollmentDrawer: React.FC<EnrollmentDrawerProps> = ({
  profile,
  isOpen,
  onClose,
  onProfileChange,
}) => {
  const [hasEntered, setHasEntered] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);
  const [isSavingConsent, setIsSavingConsent] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<SampleResult[]>([]);
  const [activePrompt, setActivePrompt] = useState<'ro' | 'ru' | 'en'>('ro');

  const panelRef = useRef<HTMLDivElement>(null);
  // Late responses for a previously opened person must not land on the current one.
  const profileIdRef = useRef<string | null>(null);

  useEffect(() => {
    profileIdRef.current = profile?.id ?? null;
    setConsentChecked(false);
    setResults([]);
    setError(null);
  }, [profile?.id, isOpen]);

  // Slide-in built from core Tailwind utilities (same pattern as DeliveryOutboxDrawer).
  useEffect(() => {
    if (!isOpen) {
      setHasEntered(false);
      return;
    }
    const frame = requestAnimationFrame(() => setHasEntered(true));
    return () => cancelAnimationFrame(frame);
  }, [isOpen]);

  // Move focus into the drawer, keep Tab inside it, close on Escape, and hand focus back on close.
  useEffect(() => {
    if (!isOpen) return;
    const panel = panelRef.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const initial = panel?.querySelector<HTMLElement>('[data-autofocus]') || panel;
    initial?.focus();

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
        return;
      }
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

    document.addEventListener('keydown', handleKey, true);
    return () => {
      document.removeEventListener('keydown', handleKey, true);
      previouslyFocused?.focus?.();
    };
  }, [isOpen, onClose]);

  if (!isOpen || !profile) return null;

  const hasConsent = Boolean(profile.consent_given_at);

  const handleGiveConsent = async () => {
    if (!consentChecked) return;
    const id = profile.id;
    setIsSavingConsent(true);
    setError(null);
    try {
      const updated = await apiClient.setVoiceConsent(id, true);
      if (profileIdRef.current !== id) return;
      onProfileChange(updated);
    } catch (err: any) {
      if (profileIdRef.current !== id) return;
      setError(err?.message || 'Consent could not be recorded.');
    } finally {
      if (profileIdRef.current === id) setIsSavingConsent(false);
    }
  };

  const handleAudioReady = async (file: File) => {
    const id = profile.id;
    setIsUploading(true);
    setError(null);
    try {
      const quality = await apiClient.uploadVoiceSample(id, file);
      if (profileIdRef.current !== id) return;
      setResults((prev) => [{ id: `${Date.now()}`, at: new Date(), quality }, ...prev]);
      // A stored sample changes the person's totals and possibly their state; refresh the summary.
      if (quality.verdict !== 'reject') {
        try {
          const refreshed = await apiClient.getVoiceProfile(id);
          if (profileIdRef.current === id) onProfileChange(refreshed);
        } catch (err) {
          console.error('Sample stored but the profile could not be refreshed:', err);
        }
      }
    } catch (err: any) {
      if (profileIdRef.current !== id) return;
      setError(err?.message || 'The sample could not be assessed.');
    } finally {
      if (profileIdRef.current === id) setIsUploading(false);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  const prompt = ENROLLMENT_PROMPTS.find((p) => p.lang === activePrompt) ?? ENROLLMENT_PROMPTS[0];
  const warnings = profile.quality_warnings ?? [];

  return (
    <div
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-end bg-slate-900/40 backdrop-blur-sm p-4"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="enroll-title"
        tabIndex={-1}
        className={`bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-2xl h-[90vh] flex flex-col overflow-hidden focus:outline-none transition duration-200 ease-out motion-reduce:transition-none ${
          hasEntered ? 'translate-x-0 opacity-100' : 'motion-safe:translate-x-8 motion-safe:opacity-0'
        }`}
      >
        {/* Header */}
        <div className="p-5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2.5 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-medpark-500 text-white flex items-center justify-center flex-shrink-0">
              <Mic className="w-4 h-4" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h3 id="enroll-title" className="font-bold text-slate-900 text-base truncate">
                Voice enrollment: {profile.person_name}
              </h3>
              <p className="text-xs text-slate-500">
                {hasConsent ? 'Step 2 of 2: record reading samples' : 'Step 1 of 2: consent'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            data-autofocus
            aria-label="Close voice enrollment"
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5" aria-busy={isUploading || isSavingConsent}>
          {error && (
            <div role="alert" className="flex items-start space-x-2 p-3 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 text-xs">
              <AlertTriangle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-px" aria-hidden="true" />
              <span className="leading-relaxed break-words">{error}</span>
            </div>
          )}

          {/* Step 1: consent gate. Nothing can be recorded before this is on record. */}
          {!hasConsent && (
            <div className="space-y-4">
              <ConsentNotice variant="full" />
              <label
                htmlFor="enroll-consent"
                className="flex items-start space-x-2.5 text-xs text-slate-800 leading-relaxed cursor-pointer"
              >
                <input
                  id="enroll-consent"
                  type="checkbox"
                  checked={consentChecked}
                  onChange={(e) => setConsentChecked(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-slate-300 text-medpark-600 focus:ring-medpark-500"
                />
                <span>
                  I am <strong>{profile.person_name}</strong>, I have read the statement above
                  (version {CONSENT_STATEMENT_VERSION}) and I agree to it. Nobody else may tick this
                  box on my behalf.
                </span>
              </label>
              <div className="flex items-center justify-end space-x-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
                >
                  Not now
                </button>
                <button
                  type="button"
                  onClick={handleGiveConsent}
                  disabled={!consentChecked || isSavingConsent}
                  className="inline-flex items-center space-x-1.5 px-4 py-2 text-xs font-bold bg-medpark-500 hover:bg-medpark-600 text-white rounded-lg shadow-xs transition-colors disabled:bg-slate-200 disabled:text-slate-500 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 focus-visible:ring-offset-1"
                >
                  {isSavingConsent ? (
                    <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />
                  ) : (
                    <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" />
                  )}
                  <span>Record consent and continue</span>
                </button>
              </div>
            </div>
          )}

          {/* Step 2: recording under the fixed prompt. */}
          {hasConsent && (
            <>
              {/* Progress toward an accepted voiceprint */}
              <div className="rounded-xl border border-slate-200 p-4 grid grid-cols-3 gap-3 text-xs">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">State</p>
                  <p
                    className={`font-bold ${
                      profile.state === 'enrolled' ? 'text-emerald-700' : 'text-slate-800'
                    }`}
                  >
                    {profile.state === 'enrolled'
                      ? 'Enrolled'
                      : profile.state === 'needs_reenrollment'
                        ? 'Needs re-enrollment'
                        : 'Not enrolled yet'}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Samples stored</p>
                  <p className="font-bold text-slate-800 tabular-nums">{profile.sample_count}</p>
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Clear speech</p>
                  <p className="font-bold text-slate-800 tabular-nums">
                    {formatSpeechSeconds(profile.total_sample_seconds)}
                  </p>
                </div>
                {warnings.length > 0 ? (
                  <ul className="col-span-3 rounded-lg border border-amber-200 bg-amber-50 p-2.5 space-y-1 text-amber-900">
                    {warnings.map((w, idx) => (
                      <li key={idx} className="flex items-start space-x-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-px" aria-hidden="true" />
                        <span className="leading-relaxed">{w}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  profile.state !== 'enrolled' && (
                    <p className="col-span-3 flex items-start space-x-1.5 text-slate-500">
                      <Info className="w-3.5 h-3.5 text-slate-400 flex-shrink-0 mt-px" aria-hidden="true" />
                      <span>
                        Enrollment completes on its own once enough clear, consistent speech is stored
                        (typically two or three passages). The server tells you here what is still missing.
                      </span>
                    </p>
                  )
                )}
              </div>

              {/* How to record */}
              <ol className="text-xs text-slate-600 leading-relaxed list-decimal list-inside space-y-0.5">
                <li>Sit where you usually sit and use the room microphone, not a headset.</li>
                <li>Read one passage below in your normal meeting voice; do not speak over anyone.</li>
                <li>Stop after the passage (about 20 seconds). Repeat with another passage.</li>
              </ol>

              {/* Fixed prompt, one language at a time */}
              <div className="rounded-xl border border-medpark-200 bg-medpark-50/60 overflow-hidden">
                <div role="tablist" aria-label="Reading passage language" className="flex border-b border-medpark-200 bg-white">
                  {ENROLLMENT_PROMPTS.map((p) => (
                    <button
                      key={p.lang}
                      role="tab"
                      type="button"
                      aria-selected={activePrompt === p.lang}
                      onClick={() => setActivePrompt(p.lang)}
                      className={`px-4 py-2 text-xs font-bold border-b-2 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-medpark-500 ${
                        activePrompt === p.lang
                          ? 'border-medpark-500 text-medpark-700'
                          : 'border-transparent text-slate-500 hover:text-slate-800'
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
                <blockquote
                  role="tabpanel"
                  lang={prompt.lang}
                  className="p-4 text-base text-slate-900 leading-relaxed font-medium"
                >
                  {prompt.text}
                </blockquote>
              </div>

              {/* Recorder */}
              <div className="rounded-xl border border-slate-200 p-4 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-bold text-slate-800">Record a sample</p>
                  {isUploading && (
                    <span role="status" className="inline-flex items-center space-x-1.5 text-xs text-slate-500">
                      <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />
                      <span>Assessing sample...</span>
                    </span>
                  )}
                </div>
                <AudioRecorder onAudioReady={handleAudioReady} disabled={isUploading} />
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Each sample is assessed on the server. A rejected sample stores nothing. Meeting
                  recordings are never used for enrollment.
                </p>
              </div>

              {/* Verbatim sample verdicts, newest first */}
              {results.length > 0 && (
                <section aria-label="Sample results" className="space-y-2">
                  <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Sample results (this session)
                  </h4>
                  <ul className="space-y-2">
                    {results.map((r) => (
                      <SampleQualityCard key={r.id} result={r} />
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </div>

        {hasConsent && (
          <div className="p-4 bg-slate-50 border-t border-slate-200 flex items-center justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-bold bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
