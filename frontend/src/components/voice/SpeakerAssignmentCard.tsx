import React, { useEffect, useState } from 'react';
import {
  Users,
  UserCheck,
  CheckCircle2,
  Save,
  RotateCcw,
  Sparkles,
  ShieldCheck,
  Loader2,
  AlertCircle,
  X,
  Mic,
  Clock,
} from 'lucide-react';
import { Attendee, SpeakerCluster, VoiceProfile, BulkSpeakerAssignmentItem } from '../../types';
import { apiClient } from '../../api/client';
import { useToast } from '../Toast';

interface SpeakerAssignmentCardProps {
  meetingId: string;
  revision: number | null;
  attendees?: Attendee[];
  onAttributionChanged?: () => void;
  className?: string;
  compact?: boolean;
}

const formatDuration = (seconds: number): string => {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${s.toString().padStart(2, '0')}s`;
};

export const SpeakerAssignmentCard: React.FC<SpeakerAssignmentCardProps> = ({
  meetingId,
  revision,
  attendees = [],
  onAttributionChanged,
  className = '',
  compact = false,
}) => {
  const { showToast } = useToast();
  const [clusters, setClusters] = useState<SpeakerCluster[]>([]);
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // cluster_id -> assigned name or designation
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [initialAssignments, setInitialAssignments] = useState<Record<string, string>>({});

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [speakersRes, profilesRes] = await Promise.all([
        apiClient.getSpeakers(meetingId),
        apiClient.listVoiceProfiles().catch(() => [] as VoiceProfile[]),
      ]);

      setClusters(speakersRes.clusters || []);
      setProfiles(profilesRes || []);

      const initMap: Record<string, string> = {};
      (speakersRes.clusters || []).forEach((c) => {
        initMap[c.cluster_id] = c.current_label || c.confirmed_name || '';
      });
      setAssignments(initMap);
      setInitialAssignments(initMap);
    } catch (err: any) {
      console.warn('Failed to load speakers for assignment card:', err);
      setError(err?.message || 'Failed to load speaker clusters');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (meetingId) {
      loadData();
    }
  }, [meetingId, revision]);

  const hasChanges = Object.keys(assignments).some(
    (k) => (assignments[k] || '').trim() !== (initialAssignments[k] || '').trim()
  );

  const handleSelectPerson = (clusterId: string, value: string) => {
    setAssignments((prev) => ({
      ...prev,
      [clusterId]: value,
    }));
  };

  const handleTextChange = (clusterId: string, text: string) => {
    setAssignments((prev) => ({
      ...prev,
      [clusterId]: text,
    }));
  };

  const handleClear = (clusterId: string) => {
    setAssignments((prev) => ({
      ...prev,
      [clusterId]: '',
    }));
  };

  const handleReset = () => {
    setAssignments({ ...initialAssignments });
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const items: BulkSpeakerAssignmentItem[] = [];

      clusters.forEach((c) => {
        const current = (assignments[c.cluster_id] || '').trim();
        const initial = (initialAssignments[c.cluster_id] || '').trim();

        if (current !== initial || current) {
          if (current) {
            // Check if matches an attendee
            const att = attendees.find((a) => a.name.toLowerCase() === current.toLowerCase());
            items.push({
              cluster_id: c.cluster_id,
              attendee_id: att ? att.id : undefined,
              display_label: current,
              action: 'label',
            });
          } else if (initial && !current) {
            // Cleared previously assigned name
            items.push({
              cluster_id: c.cluster_id,
              action: 'reject',
            });
          }
        }
      });

      if (items.length === 0) {
        setIsSaving(false);
        return;
      }

      await apiClient.bulkAssignSpeakers(meetingId, {
        assignments: items,
        expected_revision: revision ?? undefined,
        reviewer_name: 'Administrator',
        reviewer_role: 'Reviewer',
      });

      showToast(
        'Speakers Assigned',
        'Speaker names updated across transcript, minutes, and documents.',
        'success'
      );
      setInitialAssignments({ ...assignments });
      if (onAttributionChanged) {
        onAttributionChanged();
      }
    } catch (err: any) {
      console.error('Failed to save speaker assignments:', err);
      setError(err?.message || 'Failed to save speaker assignments');
      showToast('Assignment Failed', err?.message || 'Could not update speaker names', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className={`p-4 bg-white border border-slate-200 rounded-2xl flex items-center justify-center space-x-2 text-xs text-slate-500 ${className}`}>
        <Loader2 className="w-4 h-4 animate-spin text-medpark-500" />
        <span>Loading speaker attribution workspace...</span>
      </div>
    );
  }

  if (clusters.length === 0) {
    return null; // No clusters detected yet (e.g. before diarization)
  }

  const assignedCount = clusters.filter(
    (c) => Boolean((assignments[c.cluster_id] || '').trim())
  ).length;
  const isFullyAssigned = assignedCount === clusters.length && clusters.length > 0;

  return (
    <div className={`bg-white border border-slate-200 rounded-2xl shadow-xs overflow-hidden ${className}`}>
      {/* Header */}
      <div className="p-4 bg-gradient-to-r from-slate-50 to-white border-b border-slate-200 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${
            isFullyAssigned ? 'bg-emerald-100 text-emerald-700' : 'bg-medpark-50 text-medpark-600'
          }`}>
            {isFullyAssigned ? <UserCheck className="w-5 h-5" /> : <Users className="w-5 h-5" />}
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h3 className="text-sm font-bold text-slate-900">
                Speaker Identification & Designation
              </h3>
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wide bg-blue-50 text-blue-700 border border-blue-200">
                <ShieldCheck className="w-3 h-3 mr-1 text-blue-600" />
                EU AI Act Human-in-the-Loop
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Assign clinician names or clinical designations to anonymous acoustic clusters. Updates transcript, minutes, and PDF/DOCX exports.
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2 self-start md:self-auto">
          <span className={`px-2.5 py-1 rounded-lg text-xs font-semibold border ${
            isFullyAssigned
              ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
              : assignedCount > 0
              ? 'bg-amber-50 text-amber-800 border-amber-200'
              : 'bg-slate-100 text-slate-700 border-slate-200'
          }`}>
            {assignedCount}/{clusters.length} Speakers Identified
          </span>
        </div>
      </div>

      {error && (
        <div className="mx-4 mt-3 p-3 bg-rose-50 border border-rose-200 rounded-xl flex items-center space-x-2 text-xs text-rose-800">
          <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Speaker Rows */}
      <div className="p-4 space-y-3">
        {clusters.map((cluster) => {
          const currentVal = assignments[cluster.cluster_id] || '';
          const isAssigned = Boolean(currentVal.trim());

          return (
            <div
              key={cluster.cluster_id}
              className={`p-3 rounded-xl border transition-all ${
                isAssigned
                  ? 'bg-slate-50/70 border-slate-200'
                  : 'bg-amber-50/30 border-amber-200/60'
              }`}
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                {/* Cluster Meta */}
                <div className="flex items-center space-x-3 min-w-0 sm:w-1/3">
                  <div className="w-8 h-8 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-slate-700 shadow-2xs flex-shrink-0">
                    <Mic className="w-4 h-4 text-medpark-600" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-bold text-slate-900 truncate">
                        {cluster.display_label}
                      </span>
                      {isAssigned ? (
                        <span className="inline-flex items-center space-x-0.5 text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-1.5 py-0.2 rounded border border-emerald-200">
                          <CheckCircle2 className="w-2.5 h-2.5" />
                          <span>Assigned</span>
                        </span>
                      ) : (
                        <span className="text-[10px] font-medium text-slate-400 bg-white px-1.5 py-0.2 rounded border border-slate-200">
                          Anonymous
                        </span>
                      )}
                    </div>
                    <div className="flex items-center space-x-2 text-[11px] text-slate-500 mt-0.5">
                      <span className="flex items-center space-x-1">
                        <Clock className="w-3 h-3 text-slate-400" />
                        <span>{formatDuration(cluster.total_speech_seconds)}</span>
                      </span>
                      <span>&middot;</span>
                      <span>{cluster.turn_count} turns</span>
                    </div>
                  </div>
                </div>

                {/* Dropdown Select & Text Input */}
                <div className="flex-1 flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                  {/* Attendee / Staff Dropdown */}
                  <select
                    value=""
                    onChange={(e) => {
                      if (e.target.value) {
                        handleSelectPerson(cluster.cluster_id, e.target.value);
                      }
                    }}
                    className="text-xs py-1.5 px-2 bg-white rounded-lg border border-slate-300 text-slate-700 focus:outline-none focus:ring-2 focus:ring-medpark-500/20 sm:w-44 flex-shrink-0"
                    title="Quick pick from roster or meeting attendees"
                  >
                    <option value="">Quick pick attendee...</option>
                    {attendees.length > 0 && (
                      <optgroup label="Meeting Attendees">
                        {attendees.map((att) => (
                          <option key={att.id} value={att.name}>
                            {att.name} {att.role ? `(${att.role})` : ''}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    {profiles.length > 0 && (
                      <optgroup label="Registered Hospital Staff">
                        {profiles
                          .filter((p) => !attendees.some((a) => a.name.toLowerCase() === p.person_name.toLowerCase()))
                          .slice(0, 15)
                          .map((p) => (
                            <option key={p.id} value={p.person_name}>
                              {p.title ? `${p.title} ` : ''}{p.person_name} ({p.department || p.role || 'Staff'})
                            </option>
                          ))}
                      </optgroup>
                    )}
                  </select>

                  {/* Free-Text Input */}
                  <div className="relative flex-1">
                    <input
                      type="text"
                      value={currentVal}
                      onChange={(e) => handleTextChange(cluster.cluster_id, e.target.value)}
                      placeholder="Type name or clinical designation (e.g. Dr. Popescu, Chirurg)..."
                      className="w-full text-xs py-1.5 pl-3 pr-7 bg-white rounded-lg border border-slate-300 text-slate-900 focus:outline-none focus:ring-2 focus:ring-medpark-500/20 focus:border-medpark-500"
                    />
                    {currentVal && (
                      <button
                        type="button"
                        onClick={() => handleClear(cluster.cluster_id)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-0.5"
                        title="Clear speaker assignment"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer / Actions */}
      <div className="p-3.5 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
        <div className="flex items-center space-x-2 text-slate-500">
          <Sparkles className="w-3.5 h-3.5 text-medpark-600 flex-shrink-0" />
          <span>
            Applying updates names in transcript, action items, evidence quotes, and PDF/DOCX documents.
          </span>
        </div>

        <div className="flex items-center space-x-2 self-end sm:self-auto flex-shrink-0">
          {hasChanges && (
            <button
              type="button"
              onClick={handleReset}
              disabled={isSaving}
              className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg text-slate-600 hover:text-slate-800 hover:bg-slate-200 transition-colors font-medium border border-slate-200 bg-white"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Discard</span>
            </button>
          )}

          <button
            type="button"
            onClick={handleSave}
            disabled={!hasChanges || isSaving}
            className={`inline-flex items-center space-x-1.5 px-4 py-1.5 rounded-lg text-xs font-bold transition-all shadow-xs ${
              hasChanges && !isSaving
                ? 'bg-medpark-600 hover:bg-medpark-700 text-white'
                : 'bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed'
            }`}
          >
            {isSaving ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Saving assignments...</span>
              </>
            ) : (
              <>
                <Save className="w-3.5 h-3.5" />
                <span>Apply Speaker Names</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
