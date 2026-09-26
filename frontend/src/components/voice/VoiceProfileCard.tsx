import React from 'react';
import {
  CheckCircle2,
  Circle,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  Mic,
  Trash2,
  AlertTriangle,
  Clock,
} from 'lucide-react';
import { VoiceProfile, EnrollmentState } from '../../types';

interface VoiceProfileCardProps {
  profile: VoiceProfile;
  // Null when the embedder is available; otherwise the reason recording is disabled.
  recordingBlockedReason: string | null;
  onEnroll: (profile: VoiceProfile) => void;
  onWipeSamples: (profile: VoiceProfile) => void;
  onWithdrawConsent: (profile: VoiceProfile) => void;
  onDelete: (profile: VoiceProfile) => void;
}

type IconComponent = React.FC<{ className?: string }>;

const STATE_META: Record<EnrollmentState, { label: string; className: string; Icon: IconComponent }> = {
  enrolled: {
    label: 'Enrolled',
    className: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    Icon: CheckCircle2,
  },
  not_enrolled: {
    label: 'Not enrolled',
    className: 'bg-slate-100 text-slate-600 border-slate-200',
    Icon: Circle,
  },
  needs_reenrollment: {
    label: 'Needs re-enrollment',
    className: 'bg-amber-50 text-amber-900 border-amber-300',
    Icon: RefreshCw,
  },
};

export const formatSpeechSeconds = (seconds: number): string => {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m} m ${s.toString().padStart(2, '0')} s`;
};

const formatDate = (iso?: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString();
};

export const VoiceProfileCard: React.FC<VoiceProfileCardProps> = ({
  profile,
  recordingBlockedReason,
  onEnroll,
  onWipeSamples,
  onWithdrawConsent,
  onDelete,
}) => {
  const state = STATE_META[profile.state] ?? STATE_META.not_enrolled;
  const StateIcon = state.Icon;
  const hasConsent = Boolean(profile.consent_given_at);
  const hasSamples = profile.sample_count > 0;
  const warnings = profile.quality_warnings ?? [];
  const enrolledAt = formatDate(profile.enrolled_at);
  const lastUsedAt = formatDate(profile.last_used_at);
  const consentAt = formatDate(profile.consent_given_at);

  const primaryLabel = !hasConsent
    ? 'Consent & enroll'
    : profile.state === 'enrolled'
      ? 'Add samples'
      : hasSamples
        ? 'Continue enrollment'
        : 'Record samples';

  return (
    <article
      aria-label={`Voice profile: ${profile.person_name}`}
      className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 flex flex-col gap-4"
    >
      {/* Identity */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-slate-900 truncate" title={profile.person_name}>
            {profile.person_name}
          </h3>
          <p className="text-xs text-slate-500 truncate">
            {profile.role || 'Member'}
            {profile.email && (
              <>
                <span className="mx-1.5 text-slate-300" aria-hidden="true">
                  &middot;
                </span>
                <span className="font-mono">{profile.email}</span>
              </>
            )}
          </p>
        </div>
        <span
          className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[11px] font-bold border flex-shrink-0 ${state.className}`}
        >
          <StateIcon className="w-3.5 h-3.5" />
          <span>{state.label}</span>
        </span>
      </div>

      {/* Consent + enrollment facts */}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div className="col-span-2 flex items-center space-x-1.5">
          {hasConsent ? (
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" aria-hidden="true" />
          ) : (
            <ShieldOff className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" aria-hidden="true" />
          )}
          <dt className="sr-only">Consent</dt>
          <dd className={hasConsent ? 'text-emerald-800 font-semibold' : 'text-slate-500 font-medium'}>
            {hasConsent ? `Consent given ${consentAt ?? ''}` : 'No consent on record'}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Samples</dt>
          <dd className="font-semibold text-slate-800 tabular-nums">{profile.sample_count}</dd>
        </div>
        <div>
          <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Clear speech</dt>
          <dd className="font-semibold text-slate-800 tabular-nums">
            {formatSpeechSeconds(profile.total_sample_seconds)}
          </dd>
        </div>
        {enrolledAt && (
          <div className="col-span-2 flex items-center space-x-1.5 text-slate-500">
            <Clock className="w-3 h-3 text-slate-400 flex-shrink-0" aria-hidden="true" />
            <dt className="sr-only">Enrolled at</dt>
            <dd className="tabular-nums">Enrolled {enrolledAt}</dd>
          </div>
        )}
        {lastUsedAt && (
          <div className="col-span-2 flex items-center space-x-1.5 text-slate-500">
            <Clock className="w-3 h-3 text-slate-400 flex-shrink-0" aria-hidden="true" />
            <dt className="sr-only">Last confirmed on a meeting</dt>
            <dd className="tabular-nums">Last confirmed on a meeting {lastUsedAt}</dd>
          </div>
        )}
        <div className="col-span-2">
          <dt className="sr-only">Embedding model</dt>
          <dd
            className="text-[10px] font-mono text-slate-400 truncate"
            title={`${profile.embedding_model} ${profile.embedding_model_version}`}
          >
            {profile.embedding_model} &middot; {profile.embedding_model_version}
          </dd>
        </div>
      </dl>

      {/* Backend quality warnings, verbatim: they say exactly what is still missing. */}
      {warnings.length > 0 && (
        <ul className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 space-y-1 text-xs text-amber-900">
          {warnings.map((w, idx) => (
            <li key={idx} className="flex items-start space-x-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-px" aria-hidden="true" />
              <span className="leading-relaxed">{w}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Actions */}
      <div className="mt-auto flex items-center justify-between gap-2 pt-3 border-t border-slate-100">
        <button
          type="button"
          onClick={() => onEnroll(profile)}
          disabled={recordingBlockedReason !== null}
          title={recordingBlockedReason ?? primaryLabel}
          className="inline-flex items-center space-x-1.5 px-3 py-2 bg-medpark-500 hover:bg-medpark-600 text-white text-xs font-bold rounded-lg shadow-xs transition-colors disabled:bg-slate-200 disabled:text-slate-500 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 focus-visible:ring-offset-1"
        >
          <Mic className="w-3.5 h-3.5" aria-hidden="true" />
          <span>{primaryLabel}</span>
        </button>

        <div className="flex items-center space-x-1">
          {hasSamples && (
            <button
              type="button"
              onClick={() => onWipeSamples(profile)}
              aria-label={`Re-enroll ${profile.person_name}: remove all samples and the voiceprint`}
              title="Re-enroll: remove all samples and the voiceprint"
              className="p-2 text-slate-400 hover:text-amber-700 hover:bg-amber-50 rounded-lg border border-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
            </button>
          )}
          {hasConsent && (
            <button
              type="button"
              onClick={() => onWithdrawConsent(profile)}
              aria-label={`Withdraw consent for ${profile.person_name}`}
              title="Withdraw consent (deletes voiceprint and samples)"
              className="p-2 text-slate-400 hover:text-amber-700 hover:bg-amber-50 rounded-lg border border-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
            >
              <ShieldOff className="w-4 h-4" aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            onClick={() => onDelete(profile)}
            aria-label={`Delete ${profile.person_name}`}
            title="Delete person"
            className="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg border border-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
          >
            <Trash2 className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </article>
  );
};
