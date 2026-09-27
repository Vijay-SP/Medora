import React, { useEffect, useRef, useState } from 'react';
import {
  User,
  HelpCircle,
  CheckCircle2,
  PenLine,
  Play,
  RefreshCw,
  Loader2,
  AlertTriangle,
  ChevronDown,
  Users,
  Info,
  Headphones,
  GitMerge,
} from 'lucide-react';
import {
  SpeakersResponse,
  SpeakerCluster,
  SpeakerLabelOption,
  VoiceProfile,
  SpeakerDecisionAction,
  Attendee,
} from '../../types';
import { apiClient } from '../../api/client';
import { useToast } from '../Toast';
import { SpeakerAssignmentCard } from './SpeakerAssignmentCard';

interface SpeakerConfirmationPanelProps {
  meetingId: string;
  // Revision of the minutes currently on screen; a confirmation is bound to one revision.
  revision: number | null;
  attendees?: Attendee[];
  // Plays a clip; end is optional so an unchanged (seconds) => void seeker still works.
  onSeek: (start: number, end?: number) => void;
  // Playback position, used to count how much of the sampled audio was actually heard.
  currentTime?: number;
  // Fired after any recorded decision: the transcript and minutes on the server have changed.
  onAttributionChanged?: () => void;
  // Bump to refetch (e.g. after a pipeline run completes).
  reloadKey?: number;
}

const formatClock = (seconds: number): string => {
  const total = Math.max(0, Math.floor(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
};

const formatDuration = (seconds: number): string => {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m} m ${s.toString().padStart(2, '0')} s`;
};

// Per-cluster, per-turn seconds actually heard. Never inferred from a click: only from playback time.
type ListenedMap = Record<string, Record<string, number>>;

// ---------------------------------------------------------------------------------------------
// Reviewer labels: a name that goes on the cluster without a voiceprint. Either a meeting attendee
// (roster person or client-side guest, by id) or free text typed here. `name` is only for the toast.
// ---------------------------------------------------------------------------------------------
export interface LabelChoice {
  name: string;
  display_label?: string;
  attendee_id?: string;
}

const LABEL_MIN = 2;
const LABEL_MAX = 60;
// Same limits and wording as the backend's validate_label (speakers.py) so a client-side rejection
// reads exactly like a 400 would.
const ANON_LABEL_RE = /^(Speaker \d+|S\d+)$/i;

export const validateCustomLabel = (raw: string): string | null => {
  const value = raw.trim();
  if (value.length < LABEL_MIN || value.length > LABEL_MAX) {
    return `display_label must be ${LABEL_MIN}-${LABEL_MAX} characters after trimming`;
  }
  if (ANON_LABEL_RE.test(value)) {
    return `'${value}' is an anonymous speaker label, not a name; type the person's name or pick an attendee`;
  }
  return null;
};

// ---------------------------------------------------------------------------------------------
// "Someone else" menu: three sections (enrolled voices, meeting attendees & guests, custom label),
// keyboard navigable, focus returns to the trigger. The custom label is an inline row inside the
// same menu: Enter submits, Escape steps back to the menu, arrows stay inert while typing.
// ---------------------------------------------------------------------------------------------
interface PersonMenuProps {
  label: string;
  people: VoiceProfile[];
  excludeIds: string[];
  // Meeting attendees and guests; undefined when the backend does not provide them yet.
  labelOptions?: SpeakerLabelOption[];
  // The label currently on the cluster (pre-fills the custom row so it can be edited, not retyped).
  currentLabel?: string | null;
  disabled: boolean;
  onPick: (profile: VoiceProfile) => void;
  onPickLabel: (choice: LabelChoice) => void;
}

const PersonMenu: React.FC<PersonMenuProps> = ({
  label,
  people,
  excludeIds,
  labelOptions,
  currentLabel,
  disabled,
  onPick,
  onPickLabel,
}) => {
  const [open, setOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [customValue, setCustomValue] = useState('');
  const [customError, setCustomError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const customItemRef = useRef<HTMLButtonElement>(null);
  const customInputRef = useRef<HTMLInputElement>(null);
  const options = people.filter((p) => !excludeIds.includes(p.id));
  const attendees = labelOptions ?? [];

  const close = () => {
    setOpen(false);
    setCustomOpen(false);
    setCustomError(null);
  };

  useEffect(() => {
    if (!open) return;
    const items = listRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]');
    items?.[0]?.focus();

    const handleKey = (e: KeyboardEvent) => {
      const list = listRef.current;
      if (!list) return;
      // While the custom-label input owns focus, arrows edit text; only Escape is intercepted here.
      if (document.activeElement === customInputRef.current) {
        if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          setCustomOpen(false);
          setCustomError(null);
          window.setTimeout(() => customItemRef.current?.focus(), 0);
        } else if (e.key === 'Tab') {
          close();
        }
        return;
      }
      const nodes = Array.from(list.querySelectorAll<HTMLElement>('[role="menuitem"]'));
      const idx = nodes.indexOf(document.activeElement as HTMLElement);
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        close();
        triggerRef.current?.focus();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        nodes[(idx + 1) % nodes.length]?.focus();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        nodes[(idx - 1 + nodes.length) % nodes.length]?.focus();
      } else if (e.key === 'Tab') {
        close();
      }
    };
    const handleClick = (e: MouseEvent) => {
      if (!listRef.current?.contains(e.target as Node) && e.target !== triggerRef.current) {
        close();
      }
    };
    document.addEventListener('keydown', handleKey, true);
    document.addEventListener('mousedown', handleClick);
    return () => {
      document.removeEventListener('keydown', handleKey, true);
      document.removeEventListener('mousedown', handleClick);
    };
  }, [open]);

  // Opening the custom row moves focus into the input; the menu's arrow handler stands down there.
  useEffect(() => {
    if (open && customOpen) customInputRef.current?.focus();
  }, [open, customOpen]);

  const pickProfile = (p: VoiceProfile) => {
    close();
    triggerRef.current?.focus();
    onPick(p);
  };

  const pickAttendee = (a: SpeakerLabelOption) => {
    close();
    triggerRef.current?.focus();
    onPickLabel({ name: a.name, attendee_id: a.id });
  };

  const submitCustom = () => {
    if (disabled) return;
    const err = validateCustomLabel(customValue);
    if (err) {
      setCustomError(err);
      customInputRef.current?.focus();
      return;
    }
    const value = customValue.trim();
    close();
    triggerRef.current?.focus();
    onPickLabel({ name: value, display_label: value });
  };

  const openCustom = () => {
    setCustomValue(currentLabel ?? '');
    setCustomError(null);
    setCustomOpen(true);
  };

  const itemClass =
    'w-full text-left px-3 py-2 rounded-lg text-xs hover:bg-medpark-50 focus:outline-none focus-visible:bg-medpark-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-medpark-500';
  const eyebrowClass = 'px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500';

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
        className="w-full inline-flex items-center justify-center space-x-1.5 px-3 py-2 text-xs font-bold bg-white border border-slate-300 text-slate-800 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
      >
        <span>{label}</span>
        <ChevronDown className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
      </button>
      {open && (
        <div
          ref={listRef}
          role="menu"
          aria-label="Identify this speaker"
          className="absolute z-30 mt-1 left-0 right-0 min-w-[16rem] bg-white border border-slate-200 rounded-xl shadow-xl p-1 max-h-80 overflow-y-auto"
        >
          {/* Section 1: enrolled voice profiles (a voiceprint match; the only path to "confirmed"). */}
          <div role="group" aria-label="Enrolled voice profiles">
            <p className={eyebrowClass}>Enrolled voice profiles</p>
            {options.length === 0 ? (
              <p className="px-3 pb-2 text-xs text-slate-500 leading-relaxed">
                No other enrolled voice to choose from. Enroll people on the People &amp; Voices page,
                then use Re-match.
              </p>
            ) : (
              options.map((p) => (
                <button key={p.id} type="button" role="menuitem" onClick={() => pickProfile(p)} className={itemClass}>
                  <span className="font-semibold text-slate-900">{p.person_name}</span>
                  {p.role && <span className="text-slate-500"> &middot; {p.role}</span>}
                </button>
              ))
            )}
          </div>

          {/* Section 2: meeting attendees and guests (a label, no voiceprint). Hidden on older backends. */}
          {labelOptions !== undefined && (
            <div role="group" aria-label="Meeting attendees and guests" className="mt-1 pt-1 border-t border-slate-100">
              <p className={eyebrowClass}>Meeting attendees &amp; guests</p>
              {attendees.length === 0 ? (
                <p className="px-3 pb-2 text-xs text-slate-500 leading-relaxed">
                  This meeting has no attendees listed.
                </p>
              ) : (
                attendees.map((a) => (
                  <button key={a.id} type="button" role="menuitem" onClick={() => pickAttendee(a)} className={itemClass}>
                    <span className="font-semibold text-slate-900">{a.name}</span>
                    {a.role && <span className="text-slate-500"> &middot; {a.role}</span>}
                    {a.is_guest && (
                      <span className="ml-1.5 inline-block align-middle px-1.5 py-px rounded-md border border-slate-200 bg-slate-50 text-[10px] font-semibold text-slate-600">
                        Guest
                      </span>
                    )}
                  </button>
                ))
              )}
            </div>
          )}

          {/* Section 3: custom label, typed inline. */}
          <div role="group" aria-label="Custom label" className="mt-1 pt-1 border-t border-slate-100">
            <p className={eyebrowClass}>Custom label</p>
            {!customOpen ? (
              <button
                ref={customItemRef}
                type="button"
                role="menuitem"
                onClick={openCustom}
                className={`${itemClass} inline-flex items-center space-x-1.5`}
              >
                <PenLine className="w-3.5 h-3.5 text-medpark-600" aria-hidden="true" />
                <span className="font-semibold text-slate-900">Custom label&hellip;</span>
              </button>
            ) : (
              <div className="px-2 pb-2 space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <input
                    ref={customInputRef}
                    type="text"
                    value={customValue}
                    disabled={disabled}
                    maxLength={LABEL_MAX}
                    aria-label="Custom speaker label"
                    aria-invalid={customError ? true : undefined}
                    aria-describedby="speaker-custom-label-help"
                    placeholder="e.g., Head nurse, Dr. Popescu"
                    onChange={(e) => {
                      setCustomValue(e.target.value);
                      if (customError) setCustomError(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        submitCustom();
                      }
                    }}
                    className="min-w-0 flex-1 text-xs px-2.5 py-1.5 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20 disabled:opacity-50"
                  />
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={submitCustom}
                    className="px-2.5 py-1.5 text-xs font-bold text-white bg-medpark-500 hover:bg-medpark-600 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 focus-visible:ring-offset-1"
                  >
                    Assign
                  </button>
                </div>
                <p
                  id="speaker-custom-label-help"
                  role={customError ? 'alert' : undefined}
                  className={`text-[11px] leading-relaxed ${customError ? 'text-rose-700 font-semibold' : 'text-slate-500'}`}
                >
                  {customError ?? 'Enter assigns, Escape goes back. 2-60 characters.'}
                </p>
              </div>
            )}
          </div>

          <p className="px-3 pt-2 pb-1 text-[11px] text-slate-500 leading-relaxed border-t border-slate-100 mt-1">
            Assigned names appear inline in the minutes and transcript for this cluster&rsquo;s longer
            turns; no voiceprint is stored.
          </p>
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------------------------
// Cluster card
// ---------------------------------------------------------------------------------------------
interface ClusterCardProps {
  cluster: SpeakerCluster;
  allClusters: SpeakerCluster[];
  revision: number | null;
  people: VoiceProfile[];
  listenedSeconds: number;
  isBusy: boolean;
  onPlay: (start: number, end: number) => void;
  onDecide: (
    cluster: SpeakerCluster,
    action: SpeakerDecisionAction,
    profile?: VoiceProfile,
    label?: LabelChoice
  ) => void;
}

const ClusterCard: React.FC<ClusterCardProps> = ({
  cluster,
  allClusters,
  revision,
  people,
  listenedSeconds,
  isBusy,
  onPlay,
  onDecide,
}) => {
  const blocked = cluster.blocking_reasons.length > 0;
  const disabled = blocked || isBusy;
  const isNamed = cluster.state === 'confirmed' || cluster.state === 'corrected';
  const suggestedName = cluster.suggested_name ?? null;
  // A reviewer label lands as "corrected" with no Person behind it; the name is current_label
  // (older backends only expose it through confirmed_name).
  const assignedLabel =
    cluster.state === 'corrected' && !cluster.confirmed_profile_id
      ? (cluster.current_label ?? cluster.confirmed_name ?? null)
      : null;
  const isLabelAssigned = assignedLabel !== null;
  const confirmedName = isLabelAssigned ? assignedLabel : (cluster.confirmed_name ?? null);
  const labelMenuProps = {
    labelOptions: cluster.label_options,
    currentLabel: isLabelAssigned ? assignedLabel : null,
    onPickLabel: (choice: LabelChoice) => onDecide(cluster, 'label', undefined, choice),
  };
  const revisionMismatch =
    isNamed &&
    revision !== null &&
    cluster.confirmed_for_revision !== null &&
    cluster.confirmed_for_revision !== undefined &&
    cluster.confirmed_for_revision !== revision;

  const mergeLabels = cluster.merge_suggestion_with
    .map((id) => allClusters.find((c) => c.cluster_id === id)?.display_label ?? id)
    .filter((l) => l !== cluster.display_label);

  const suggestedProfile = people.find((p) => p.id === cluster.suggested_profile_id) ?? null;
  const confirmedProfile = people.find((p) => p.id === cluster.confirmed_profile_id) ?? null;
  // A suggestion outlives the voiceprint that produced it (deleting a person or withdrawing consent
  // does not rewrite transcripts): "Yes" is only offered while that person is still enrolled.
  const suggestionStale = cluster.state === 'suggested' && suggestedProfile?.state !== 'enrolled';

  // Confusability rules: the card's frame and its header pill are the only places state is encoded,
  // and each state has a distinct shape + icon + prefix so colour is never the only cue.
  const frameClass =
    cluster.state === 'suggested'
      ? 'border-2 border-dashed border-amber-400 bg-amber-50/40'
      : cluster.state === 'confirmed'
        ? 'border border-emerald-300 bg-white'
        : isLabelAssigned
          ? 'border border-medpark-500/50 bg-medpark-50/40'
          : cluster.state === 'corrected'
            ? 'border border-medpark-500/50 bg-white'
            : 'border border-slate-200 bg-white';

  const header = (() => {
    if (cluster.state === 'confirmed' && confirmedName) {
      return (
        <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full bg-emerald-600 text-white text-xs font-bold">
          <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
          <span>Confirmed &mdash; {confirmedName}</span>
        </span>
      );
    }
    if (isLabelAssigned && confirmedName) {
      return (
        <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full bg-white border border-medpark-500 text-medpark-700 text-xs font-bold">
          <PenLine className="w-4 h-4" aria-hidden="true" />
          <span>Assigned &mdash; {confirmedName}</span>
        </span>
      );
    }
    if (cluster.state === 'corrected' && confirmedName) {
      return (
        <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full bg-medpark-500 text-white text-xs font-bold">
          <PenLine className="w-4 h-4" aria-hidden="true" />
          <span>Corrected &mdash; {confirmedName}</span>
        </span>
      );
    }
    if (cluster.state === 'suggested' && suggestedName) {
      return (
        <span className="inline-flex items-center space-x-1.5 text-sm font-bold text-amber-900">
          <HelpCircle className="w-5 h-5 text-amber-600" aria-hidden="true" />
          <span>Is this {suggestedName}?</span>
        </span>
      );
    }
    return (
      <span className="inline-flex items-center space-x-1.5 text-sm font-bold text-slate-700">
        <User className="w-4 h-4 text-slate-400" aria-hidden="true" />
        <span>
          {cluster.display_label} &middot; not identified
        </span>
      </span>
    );
  })();

  const similarity =
    (cluster.state === 'suggested' || cluster.state === 'confirmed') && typeof cluster.match_score === 'number' ? (
      <div className="space-y-0.5 text-xs text-slate-700">
        <p>
          Similarity: <span className="font-bold">{cluster.match_band ?? 'no_match'}</span>{' '}
          <span className="tabular-nums">({cluster.match_score.toFixed(2)} cosine)</span>
          {typeof cluster.vote_ratio === 'number' && cluster.total_votes ? (
            <span className="ml-2 font-medium text-slate-600">
              &middot; Consensus: {cluster.vote_count}/{cluster.total_votes} segments ({Math.round(cluster.vote_ratio * 100)}%)
            </span>
          ) : null}
        </p>
        {cluster.reasons && cluster.reasons.length > 0 && (
          <p className="text-[11px] text-slate-500 italic">
            Factors: {cluster.reasons.join(', ')}
          </p>
        )}
      </div>
    ) : null;

  return (
    <article
      aria-label={`${cluster.display_label}: ${cluster.state}`}
      className={`rounded-2xl shadow-xs p-5 space-y-4 ${frameClass}`}
    >
      {/* Header row */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1 min-w-0">
          {header}
          <p className="text-[11px] font-semibold text-slate-500 tabular-nums">
            {cluster.display_label} &middot; {cluster.turn_count} turn{cluster.turn_count === 1 ? '' : 's'}{' '}
            &middot; {formatDuration(cluster.total_speech_seconds)} of speech
          </p>
          {similarity}
        </div>
        <span className="text-[10px] font-mono text-slate-400">{cluster.cluster_id}</span>
      </div>

      {/* Revision mismatch */}
      {revisionMismatch && (
        <div role="alert" className="flex items-start space-x-2 p-3 rounded-xl border border-amber-300 bg-amber-50 text-amber-900 text-xs">
          <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-px" aria-hidden="true" />
          <div className="space-y-1.5">
            <p className="leading-relaxed">
              Confirmed for revision <span className="tabular-nums font-bold">{cluster.confirmed_for_revision}</span>,
              but the minutes are now revision <span className="tabular-nums font-bold">{revision}</span>. Listen again
              and re-confirm so the name applies to the current document.
            </p>
            {isLabelAssigned && confirmedName && (
              <button
                type="button"
                disabled={disabled}
                onClick={() =>
                  onDecide(cluster, 'label', undefined, { name: confirmedName, display_label: confirmedName })
                }
                className="inline-flex items-center space-x-1 px-2.5 py-1 text-[11px] font-bold bg-white border border-amber-300 rounded-lg hover:bg-amber-100 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
              >
                <RefreshCw className="w-3 h-3" aria-hidden="true" />
                <span>Re-assign {confirmedName} for revision {revision}</span>
              </button>
            )}
            {!isLabelAssigned && confirmedProfile && (
              <button
                type="button"
                disabled={disabled}
                onClick={() => onDecide(cluster, 'confirm', confirmedProfile)}
                className="inline-flex items-center space-x-1 px-2.5 py-1 text-[11px] font-bold bg-white border border-amber-300 rounded-lg hover:bg-amber-100 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
              >
                <RefreshCw className="w-3 h-3" aria-hidden="true" />
                <span>Re-confirm {confirmedName} for revision {revision}</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Merge suggestion */}
      {mergeLabels.length > 0 && (
        <p className="flex items-start space-x-1.5 text-xs text-slate-600">
          <GitMerge className="w-3.5 h-3.5 text-slate-400 flex-shrink-0 mt-px" aria-hidden="true" />
          <span>
            Matches the same person as {mergeLabels.join(', ')}. This may be one voice split in two;
            decide each speaker separately.
          </span>
        </p>
      )}

      {/* Sample turns: the hardest ones for the candidate, never the longest */}
      <section aria-label={`Sample turns for ${cluster.display_label}`} className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
            {cluster.suggested_profile_id || cluster.confirmed_profile_id
              ? 'Least similar turns to the voiceprint - listen to these, not the easy ones'
              : isLabelAssigned
                ? 'Sample turns from this speaker (label assigned; no voiceprint to compare against)'
                : 'Sample turns from this speaker'}
          </p>
          <p className="inline-flex items-center space-x-1 text-[11px] font-semibold text-slate-600 tabular-nums" aria-live="polite">
            <Headphones className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
            <span>
              You have listened to {Math.round(listenedSeconds)} s of {formatDuration(cluster.total_speech_seconds)}
            </span>
          </p>
        </div>
        {cluster.sample_turns.length === 0 ? (
          <p className="text-xs text-slate-500">No sample turns were returned for this speaker.</p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
            {cluster.sample_turns.map((turn) => (
              <li key={turn.segment_id} className="flex items-start gap-3 p-2.5">
                <button
                  type="button"
                  onClick={() => onPlay(turn.start, turn.end)}
                  aria-label={`Play turn from ${formatClock(turn.start)} to ${formatClock(turn.end)}`}
                  className="inline-flex items-center space-x-1 text-xs font-mono tabular-nums text-medpark-700 hover:text-medpark-900 bg-medpark-50 hover:bg-medpark-100 px-2 py-1 rounded-md border border-medpark-500/20 transition-colors flex-shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
                >
                  <Play className="w-3 h-3 fill-medpark-600" aria-hidden="true" />
                  <span>
                    {formatClock(turn.start)}&ndash;{formatClock(turn.end)}
                  </span>
                </button>
                <p className="text-xs text-slate-800 leading-relaxed min-w-0 flex-1 break-words">{turn.text}</p>
                <span className="text-[10px] text-slate-400 tabular-nums flex-shrink-0">
                  {turn.speech_seconds.toFixed(1)} s
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[11px] text-slate-500 tabular-nums">
          Sampled {formatDuration(cluster.sampled_seconds)} of {formatDuration(cluster.total_speech_seconds)} in{' '}
          {cluster.sample_turns.length} turn{cluster.sample_turns.length === 1 ? '' : 's'}.
        </p>
      </section>

      {/* Blocking reasons: verbatim, and the decision buttons stay disabled while any exist */}
      {blocked && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 space-y-1">
          <p className="text-[11px] font-bold uppercase tracking-wider text-rose-700">
            Cannot confirm this speaker yet
          </p>
          <ul className="list-disc list-inside text-xs text-rose-800 leading-relaxed space-y-0.5">
            {cluster.blocking_reasons.map((r, idx) => (
              <li key={idx}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Decision buttons: equal width, one row */}
      {cluster.state === 'suggested' && suggestedName && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <button
            type="button"
            disabled={disabled || !suggestedProfile || suggestionStale}
            onClick={() => suggestedProfile && !suggestionStale && onDecide(cluster, 'confirm', suggestedProfile)}
            className="inline-flex items-center justify-center space-x-1.5 px-3 py-2 text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg shadow-xs transition-colors disabled:bg-slate-200 disabled:text-slate-500 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-1"
          >
            <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
            <span>Yes, this is {suggestedName}</span>
          </button>
          <PersonMenu
            label="Someone else"
            people={people}
            excludeIds={cluster.suggested_profile_id ? [cluster.suggested_profile_id] : []}
            disabled={disabled}
            onPick={(p) => onDecide(cluster, 'correct', p)}
            {...labelMenuProps}
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() => onDecide(cluster, 'unknown')}
            className="inline-flex items-center justify-center space-x-1.5 px-3 py-2 text-xs font-bold bg-white border border-slate-300 text-slate-800 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
          >
            <HelpCircle className="w-4 h-4 text-slate-500" aria-hidden="true" />
            <span>Not sure</span>
          </button>
        </div>
      )}
      {cluster.state === 'suggested' && suggestedName && suggestionStale && people.length > 0 && (
        <p className="text-[11px] text-amber-800 leading-relaxed">
          This suggestion is stale: {suggestedName} no longer has an enrolled voice (profile deleted,
          consent withdrawn, or re-enrollment pending), so it cannot be confirmed. Press Re-match to
          clear it, or choose Someone else / Not sure.
        </p>
      )}

      {cluster.state === 'anonymous' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <PersonMenu
            label="Identify this speaker"
            people={people}
            excludeIds={[]}
            disabled={disabled}
            onPick={(p) => onDecide(cluster, 'correct', p)}
            {...labelMenuProps}
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() => onDecide(cluster, 'unknown')}
            className="inline-flex items-center justify-center space-x-1.5 px-3 py-2 text-xs font-bold bg-white border border-slate-300 text-slate-800 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
          >
            <HelpCircle className="w-4 h-4 text-slate-500" aria-hidden="true" />
            <span>Not sure</span>
          </button>
        </div>
      )}

      {isNamed && (
        <>
          <p className="text-xs text-slate-600 leading-relaxed tabular-nums">
            {cluster.unprintable_turns} of {cluster.turn_count} turns in this cluster are too short to
            attribute and will show as {cluster.display_label} on the document.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <PersonMenu
              label="Change name"
              people={people}
              excludeIds={cluster.confirmed_profile_id ? [cluster.confirmed_profile_id] : []}
              disabled={disabled}
              onPick={(p) => onDecide(cluster, 'correct', p)}
              {...labelMenuProps}
            />
            <button
              type="button"
              disabled={disabled}
              onClick={() => onDecide(cluster, 'reject')}
              className="inline-flex items-center justify-center space-x-1.5 px-3 py-2 text-xs font-bold bg-white border border-rose-300 text-rose-700 rounded-lg hover:bg-rose-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
            >
              <User className="w-4 h-4" aria-hidden="true" />
              <span>Remove name (back to {cluster.display_label})</span>
            </button>
          </div>
        </>
      )}
    </article>
  );
};

// ---------------------------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------------------------
interface PendingManyToOne {
  cluster: SpeakerCluster;
  profile: VoiceProfile;
  alreadyOn: string[]; // display labels of clusters already carrying this person
}

export const SpeakerConfirmationPanel: React.FC<SpeakerConfirmationPanelProps> = ({
  meetingId,
  revision,
  attendees = [],
  onSeek,
  currentTime,
  onAttributionChanged,
  reloadKey = 0,
}) => {
  const { showToast } = useToast();
  const [data, setData] = useState<SpeakersResponse | null>(null);
  const [people, setPeople] = useState<VoiceProfile[]>([]);
  // A failed people list is surfaced, never silently rendered as "no enrolled voices".
  const [peopleError, setPeopleError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRematching, setIsRematching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewerName, setReviewerName] = useState('');
  const [reviewerRole, setReviewerRole] = useState('');
  const [reviewerHint, setReviewerHint] = useState<string | null>(null);
  const [busyClusterId, setBusyClusterId] = useState<string | null>(null);
  const [pendingManyToOne, setPendingManyToOne] = useState<PendingManyToOne | null>(null);
  const [listened, setListened] = useState<ListenedMap>({});

  const requestedIdRef = useRef<string>(meetingId);
  const lastTimeRef = useRef<number | null>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const manyToOneRef = useRef<HTMLDivElement>(null);

  // The people list is fetched beside the clusters; its failure is reported separately so the
  // clusters still render and the reviewer learns why no name can be chosen.
  const loadPeople = async (): Promise<{ people: VoiceProfile[]; error: string | null }> => {
    try {
      return { people: await apiClient.listVoiceProfiles(), error: null };
    } catch (err: any) {
      return { people: [], error: err?.message || 'Voice profiles could not be loaded.' };
    }
  };

  const load = async () => {
    const id = meetingId;
    requestedIdRef.current = id;
    setIsLoading(true);
    setError(null);
    try {
      const [speakers, profiles] = await Promise.all([apiClient.getSpeakers(id), loadPeople()]);
      if (requestedIdRef.current !== id) return;
      setData(speakers);
      if (profiles.error === null) setPeople(profiles.people);
      setPeopleError(profiles.error);
    } catch (err: any) {
      if (requestedIdRef.current !== id) return;
      setData(null);
      setError(err?.message || 'Speaker clusters could not be loaded.');
    } finally {
      if (requestedIdRef.current === id) setIsLoading(false);
    }
  };

  useEffect(() => {
    setListened({});
    lastTimeRef.current = null;
    setPendingManyToOne(null);
    load();
  }, [meetingId, reloadKey]);

  // Honest listening accounting: credit a turn only while playback time moves through it.
  useEffect(() => {
    if (typeof currentTime !== 'number' || !data) return;
    const prev = lastTimeRef.current;
    lastTimeRef.current = currentTime;
    if (prev === null) return;
    const delta = currentTime - prev;
    if (delta <= 0 || delta > 1.5) return;
    setListened((state) => {
      let changed = false;
      const next: ListenedMap = { ...state };
      for (const cluster of data.clusters) {
        for (const turn of cluster.sample_turns) {
          if (prev < turn.start - 0.05 || currentTime > turn.end + 0.05) continue;
          const cap = Math.max(0, turn.end - turn.start);
          const perCluster = next[cluster.cluster_id] ?? {};
          const already = perCluster[turn.segment_id] ?? 0;
          const credited = Math.min(cap, already + delta);
          if (credited === already) continue;
          next[cluster.cluster_id] = { ...perCluster, [turn.segment_id]: credited };
          changed = true;
        }
      }
      return changed ? next : state;
    });
  }, [currentTime, data]);

  useEffect(() => {
    if (pendingManyToOne) manyToOneRef.current?.focus();
  }, [pendingManyToOne]);

  const listenedFor = (clusterId: string): number =>
    Object.values(listened[clusterId] ?? {}).reduce((a, b) => a + b, 0);

  const enrolledPeople = people.filter((p) => p.state === 'enrolled');

  const submitDecision = async (
    cluster: SpeakerCluster,
    action: SpeakerDecisionAction,
    profile?: VoiceProfile,
    label?: LabelChoice
  ) => {
    if (!data) return;
    setBusyClusterId(cluster.cluster_id);
    try {
      await apiClient.confirmSpeaker(meetingId, cluster.cluster_id, {
        action,
        profile_id: profile?.id ?? null,
        display_label: action === 'label' ? (label?.display_label ?? null) : null,
        attendee_id: action === 'label' ? (label?.attendee_id ?? null) : null,
        expected_revision: data.current_revision,
        reviewer_name: reviewerName.trim(),
        reviewer_role: reviewerRole.trim() || 'Reviewer',
      });
      const verb =
        action === 'confirm'
          ? `confirmed as ${profile?.person_name}`
          : action === 'correct'
            ? `corrected to ${profile?.person_name}`
            : action === 'label'
              ? `assigned the name ${label?.name}`
              : action === 'reject'
                ? 'returned to anonymous'
                : 'recorded as not identified';
      showToast('Speaker decision recorded', `${cluster.display_label} ${verb}.`);
      onAttributionChanged?.();
    } catch (err: any) {
      // 409 = stale revision, blocking reasons, or an implicit many-to-one; the detail says which.
      showToast('Decision not recorded', err?.message || 'Server error', 'error');
    } finally {
      setBusyClusterId(null);
      // Any outcome may have changed revisions or other clusters: reload the truth.
      await load();
    }
  };

  const handleDecide = (
    cluster: SpeakerCluster,
    action: SpeakerDecisionAction,
    profile?: VoiceProfile,
    label?: LabelChoice
  ) => {
    if (!reviewerName.trim()) {
      setReviewerHint('Enter your name first: every decision is recorded with the reviewer who made it.');
      nameInputRef.current?.focus();
      return;
    }
    setReviewerHint(null);
    if ((action === 'confirm' || action === 'correct') && profile && data) {
      const alreadyOn = data.clusters
        .filter(
          (c) =>
            c.cluster_id !== cluster.cluster_id &&
            (c.state === 'confirmed' || c.state === 'corrected') &&
            c.confirmed_profile_id === profile.id
        )
        .map((c) => c.display_label);
      if (alreadyOn.length > 0) {
        // Many-to-one is allowed but must be explicit: ask, then send "correct".
        setPendingManyToOne({ cluster, profile, alreadyOn });
        return;
      }
    }
    submitDecision(cluster, action, profile, label);
  };

  const handleRematch = async () => {
    setIsRematching(true);
    try {
      const refreshed = await apiClient.rematchSpeakers(meetingId);
      setData(refreshed);
      const profiles = await loadPeople();
      if (profiles.error === null) setPeople(profiles.people);
      setPeopleError(profiles.error);
      showToast('Speakers re-matched', 'Suggestions were re-scored against the current enrollments.');
      onAttributionChanged?.();
    } catch (err: any) {
      showToast('Re-match failed', err?.message || 'Server error', 'error');
    } finally {
      setIsRematching(false);
    }
  };

  const counts = data
    ? {
        suggested: data.clusters.filter((c) => c.state === 'suggested').length,
        named: data.clusters.filter((c) => c.state === 'confirmed' || c.state === 'corrected').length,
        anonymous: data.clusters.filter((c) => c.state === 'anonymous').length,
      }
    : null;

  return (
    <div className="space-y-5">
      {/* Administrator Bulk Assignment Card (EU AI Act Human-in-the-Loop) */}
      <SpeakerAssignmentCard
        meetingId={meetingId}
        revision={revision}
        attendees={attendees}
        onAttributionChanged={() => {
          load();
          if (onAttributionChanged) onAttributionChanged();
        }}
      />

      {/* Header */}
      <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
          <div className="space-y-1 min-w-0">
            <h3 className="font-bold text-sm text-slate-900 flex items-center space-x-2">
              <Users className="w-4 h-4 text-medpark-600" aria-hidden="true" />
              <span>Speaker identification</span>
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed max-w-2xl">
              The system groups turns by voice and may ask whether a group is an enrolled person. Only
              your explicit confirmation, or a name you assign from the attendee list or by hand, puts a
              name on the document, and only on turns long enough to attribute; the rest stay as
              Speaker N. Listen before you decide.
            </p>
            {counts && (
              <p className="text-[11px] font-semibold text-slate-500 tabular-nums">
                {data?.clusters.length} speaker{data?.clusters.length === 1 ? '' : 's'} &middot; {counts.suggested}{' '}
                suggested &middot; {counts.named} named &middot; {counts.anonymous} anonymous &middot;{' '}
                {data?.enrolled_people ?? 0} enrolled voice{(data?.enrolled_people ?? 0) === 1 ? '' : 's'}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              type="button"
              onClick={load}
              disabled={isLoading}
              aria-label="Refresh speaker clusters"
              title="Refresh"
              className="p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={handleRematch}
              disabled={isRematching || isLoading || !data?.embedder_available}
              title="Re-score the cached voice embeddings against the current enrollments (no audio re-run)"
              className="inline-flex items-center space-x-1.5 px-3 py-2 text-xs font-bold bg-white border border-slate-300 text-slate-800 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              {isRematching ? (
                <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5 text-slate-500" aria-hidden="true" />
              )}
              <span>Re-match after new enrollments</span>
            </button>
          </div>
        </div>

        {/* Reviewer identity: typed, never pre-filled, recorded with every decision. */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-3 border-t border-slate-100">
          <div className="space-y-1">
            <label htmlFor="speaker-reviewer-name" className="text-xs font-semibold text-slate-700">
              Your name <span className="text-rose-600" aria-hidden="true">*</span>
            </label>
            <input
              ref={nameInputRef}
              id="speaker-reviewer-name"
              type="text"
              required
              aria-required="true"
              aria-describedby="speaker-reviewer-hint"
              value={reviewerName}
              onChange={(e) => {
                setReviewerName(e.target.value);
                if (e.target.value.trim()) setReviewerHint(null);
              }}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              placeholder="e.g., Dr. Elena Ceban"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="speaker-reviewer-role" className="text-xs font-semibold text-slate-700">
              Your role
            </label>
            <input
              id="speaker-reviewer-role"
              type="text"
              value={reviewerRole}
              onChange={(e) => setReviewerRole(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              placeholder="Reviewer"
            />
          </div>
          <p id="speaker-reviewer-hint" role={reviewerHint ? 'alert' : undefined} className={`sm:col-span-2 text-[11px] ${reviewerHint ? 'text-rose-700 font-semibold' : 'text-slate-500'}`}>
            {reviewerHint ?? 'Recorded with every decision, next to the revision it applies to.'}
          </p>
        </div>
      </div>

      {/* Server-side notices */}
      {data && !data.embedder_available && (
        <div role="alert" className="p-4 rounded-2xl border border-amber-300 bg-amber-50 text-amber-900 flex items-start gap-3 shadow-xs">
          <AlertTriangle className="w-5 h-5 text-amber-700 flex-shrink-0" aria-hidden="true" />
          <p className="text-xs font-semibold leading-relaxed">
            The speaker embedder was not available when this meeting was processed, so all turns are
            under one anonymous speaker and nothing can be suggested.
          </p>
        </div>
      )}
      {peopleError && (
        <div role="alert" className="p-4 rounded-2xl border border-rose-200 bg-rose-50 text-rose-900 flex items-start gap-3 shadow-xs">
          <AlertTriangle className="w-5 h-5 text-rose-600 flex-shrink-0" aria-hidden="true" />
          <div className="text-xs leading-relaxed space-y-1">
            <p className="font-bold">The list of enrolled people could not be loaded</p>
            <p className="break-words">{peopleError}</p>
            <p>
              No name can be confirmed or chosen until it loads; this is not the same as having no
              enrolled voices. Press Refresh to try again.
            </p>
          </div>
        </div>
      )}
      {data && data.embedder_available && data.enrolled_people === 0 && !peopleError && (
        <div className="p-4 rounded-2xl border border-slate-200 bg-white text-slate-700 flex items-start gap-3 shadow-xs">
          <Info className="w-5 h-5 text-slate-400 flex-shrink-0" aria-hidden="true" />
          <p className="text-xs leading-relaxed">
            No enrolled voices yet, so no name can be suggested. Enroll people on the People &amp; Voices
            page, then press Re-match. You can still mark speakers as not identified.
          </p>
        </div>
      )}
      {data && data.warnings.length > 0 && (
        <ul className="p-4 rounded-2xl border border-amber-200 bg-amber-50 text-amber-900 text-xs space-y-1 shadow-xs">
          {data.warnings.map((w, idx) => (
            <li key={idx} className="flex items-start space-x-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-px" aria-hidden="true" />
              <span className="leading-relaxed">{w}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Explicit many-to-one confirmation */}
      {pendingManyToOne && (
        <div
          ref={manyToOneRef}
          role="alertdialog"
          aria-modal="false"
          aria-labelledby="many-to-one-title"
          tabIndex={-1}
          className="p-4 rounded-2xl border-2 border-amber-400 bg-amber-50 text-amber-900 space-y-3 shadow-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
        >
          <p id="many-to-one-title" className="text-xs font-bold leading-relaxed">
            {pendingManyToOne.profile.person_name} is already confirmed as{' '}
            {pendingManyToOne.alreadyOn.join(' and ')}. Is {pendingManyToOne.cluster.display_label} also{' '}
            {pendingManyToOne.profile.person_name}?
          </p>
          <p className="text-xs leading-relaxed">
            One person can appear as two speakers (for example Romanian and Russian turns split apart).
            Confirm only if you listened to both and they are the same voice.
          </p>
          <div className="flex items-center justify-end space-x-2">
            <button
              type="button"
              onClick={() => setPendingManyToOne(null)}
              className="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                const p = pendingManyToOne;
                setPendingManyToOne(null);
                submitDecision(p.cluster, 'correct', p.profile);
              }}
              className="px-3 py-1.5 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-1"
            >
              Yes, both are {pendingManyToOne.profile.person_name}
            </button>
          </div>
        </div>
      )}

      {/* Clusters */}
      <section aria-label="Speaker clusters" aria-busy={isLoading} className="space-y-4">
        {isLoading && (
          <div role="status" className="text-center py-12 text-xs text-slate-400">
            Loading speaker clusters...
          </div>
        )}
        {!isLoading && error && (
          <div role="alert" className="p-4 rounded-2xl border border-rose-200 bg-rose-50 text-rose-800 space-y-2 shadow-xs">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 text-rose-600 flex-shrink-0" aria-hidden="true" />
              <span className="text-xs font-bold">Speaker clusters could not be loaded</span>
            </div>
            <p className="text-xs leading-relaxed">{error}</p>
            <button
              type="button"
              onClick={load}
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-bold bg-white border border-rose-200 rounded-lg text-rose-700 hover:bg-rose-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
            >
              <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Retry</span>
            </button>
          </div>
        )}
        {!isLoading && !error && data && data.clusters.length === 0 && (
          <div className="bg-white rounded-2xl border border-slate-200 p-10 shadow-xs text-center">
            <User className="w-6 h-6 text-slate-400 mx-auto" aria-hidden="true" />
            <h3 className="mt-3 text-sm font-bold text-slate-900">No speakers to review</h3>
            <p className="mt-1 text-xs text-slate-600 max-w-md mx-auto leading-relaxed">
              This meeting has no diarized speech yet. Run the pipeline first.
            </p>
          </div>
        )}
        {!isLoading &&
          data &&
          data.clusters.map((cluster) => (
            <ClusterCard
              key={cluster.cluster_id}
              cluster={cluster}
              allClusters={data.clusters}
              revision={revision}
              people={enrolledPeople}
              listenedSeconds={listenedFor(cluster.cluster_id)}
              isBusy={busyClusterId === cluster.cluster_id || pendingManyToOne !== null}
              onPlay={(start, end) => onSeek(start, end)}
              onDecide={handleDecide}
            />
          ))}
      </section>
    </div>
  );
};
