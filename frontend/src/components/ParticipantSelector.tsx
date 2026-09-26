import React, { useEffect, useMemo, useState } from 'react';
import {
  Users,
  Search,
  Plus,
  Trash2,
  Check,
  ShieldCheck,
  UserPlus,
  Filter,
  X,
  UserCheck,
} from 'lucide-react';
import { Attendee, VoiceProfile } from '../types';
import { apiClient } from '../api/client';
import { MEDPARK_DEPARTMENTS } from './voice/PeoplePage';

interface ParticipantSelectorProps {
  attendees: Attendee[];
  onChange: (attendees: Attendee[]) => void;
  disabled?: boolean;
}

export const ParticipantSelector: React.FC<ParticipantSelectorProps> = ({
  attendees,
  onChange,
  disabled = false,
}) => {
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDept, setSelectedDept] = useState('ALL');
  const [showRosterPicker, setShowRosterPicker] = useState(false);
  const [showGuestForm, setShowGuestForm] = useState(false);

  // Guest inputs
  const [guestName, setGuestName] = useState('');
  const [guestEmail, setGuestEmail] = useState('');
  const [guestRole, setGuestRole] = useState('External Guest');
  const [guestError, setGuestError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setIsLoading(true);
    apiClient
      .listVoiceProfiles()
      .then((data) => {
        if (mounted) setProfiles(data);
      })
      .catch((err) => {
        console.warn('Could not load voice profiles for participant selector:', err);
      })
      .finally(() => {
        if (mounted) setIsLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  // Set of selected person_ids or emails for fast check
  const selectedPersonIds = useMemo(() => {
    return new Set(attendees.map((a) => a.person_id).filter(Boolean));
  }, [attendees]);

  const selectedEmails = useMemo(() => {
    return new Set(attendees.map((a) => a.email.toLowerCase()).filter(Boolean));
  }, [attendees]);

  // Unique departments present in registered profiles
  const availableDepts = useMemo(() => {
    const set = new Set<string>();
    profiles.forEach((p) => {
      if (p.department) set.add(p.department);
    });
    // Add known presets that exist in profiles or just union
    return Array.from(set).sort();
  }, [profiles]);

  // Filtered roster for selection
  const filteredProfiles = useMemo(() => {
    return profiles.filter((p) => {
      if (selectedDept !== 'ALL' && p.department !== selectedDept) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = p.person_name.toLowerCase().includes(q);
        const matchesRole = (p.role || '').toLowerCase().includes(q);
        const matchesEmail = (p.email || '').toLowerCase().includes(q);
        const matchesDept = (p.department || '').toLowerCase().includes(q);
        const matchesSpec = (p.specialty || '').toLowerCase().includes(q);
        return matchesName || matchesRole || matchesEmail || matchesDept || matchesSpec;
      }
      return true;
    });
  }, [profiles, selectedDept, searchQuery]);

  const handleTogglePerson = (profile: VoiceProfile) => {
    if (disabled) return;
    const isSelected = selectedPersonIds.has(profile.id) || selectedEmails.has(profile.email.toLowerCase());
    if (isSelected) {
      // Remove
      onChange(
        attendees.filter(
          (a) => a.person_id !== profile.id && a.email.toLowerCase() !== profile.email.toLowerCase()
        )
      );
    } else {
      // Add
      const displayName = profile.title
        ? `${profile.title} ${profile.person_name}`
        : profile.person_name;
      const newAttendee: Attendee = {
        id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        person_id: profile.id,
        name: displayName,
        role: profile.role || 'Member',
        department: profile.department || undefined,
        email: profile.email || `${profile.person_name.toLowerCase().replace(/\s+/g, '.')}@medpark.md`,
      };
      onChange([...attendees, newAttendee]);
    }
  };

  const handleRemoveAttendee = (id: string) => {
    if (disabled) return;
    onChange(attendees.filter((a) => a.id !== id));
  };

  const handleAddGuest = (e: React.FormEvent) => {
    e.preventDefault();
    if (disabled) return;
    if (!guestName.trim()) {
      setGuestError('Guest name is required.');
      return;
    }
    if (!guestEmail.trim() || !guestEmail.includes('@')) {
      setGuestError('Valid email is required.');
      return;
    }

    const newGuest: Attendee = {
      id: `guest_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      name: guestName.trim(),
      role: guestRole.trim() || 'External Guest',
      department: 'Guest / External',
      email: guestEmail.trim(),
    };

    onChange([...attendees, newGuest]);
    setGuestName('');
    setGuestEmail('');
    setGuestRole('External Guest');
    setGuestError(null);
    setShowGuestForm(false);
  };

  return (
    <div className="space-y-3">
      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div className="flex items-center space-x-2">
          <Users className="w-4 h-4 text-slate-500" aria-hidden="true" />
          <span className="text-xs font-bold text-slate-800">
            Meeting Participants ({attendees.length})
          </span>
          <span className="text-[11px] text-slate-400 font-normal">
            ({attendees.filter((a) => a.person_id).length} staff, {attendees.filter((a) => !a.person_id).length} guests)
          </span>
        </div>

        <div className="flex items-center gap-1.5 self-start sm:self-auto">
          <button
            type="button"
            onClick={() => {
              setShowRosterPicker((prev) => !prev);
              setShowGuestForm(false);
            }}
            disabled={disabled}
            className={`inline-flex items-center space-x-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-colors border ${
              showRosterPicker
                ? 'bg-medpark-50 text-medpark-700 border-medpark-200 shadow-xs'
                : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
            }`}
          >
            <UserCheck className="w-3.5 h-3.5 text-medpark-600" />
            <span>Select Staff ({profiles.length})</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setShowGuestForm((prev) => !prev);
              setShowRosterPicker(false);
            }}
            disabled={disabled}
            className={`inline-flex items-center space-x-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-colors border ${
              showGuestForm
                ? 'bg-amber-50 text-amber-800 border-amber-300 shadow-xs'
                : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
            }`}
          >
            <UserPlus className="w-3.5 h-3.5 text-amber-600" />
            <span>+ Guest</span>
          </button>
        </div>
      </div>

      {/* Slide-out / Collapsible Staff Picker */}
      {showRosterPicker && (
        <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-xl space-y-3 shadow-inner">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-900 flex items-center space-x-1.5">
              <span>Choose Registered Medical Staff</span>
              <span className="text-[10px] font-normal text-slate-500">
                (links voiceprints to speaker attribution)
              </span>
            </span>
            <button
              type="button"
              onClick={() => setShowRosterPicker(false)}
              className="text-slate-400 hover:text-slate-600 p-0.5 rounded-md"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Search + Department Filter */}
          <div className="space-y-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search staff by name, role, department or specialty..."
                className="w-full pl-8 pr-7 py-1.5 text-xs bg-white rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>

            {/* Department Pills */}
            <div className="flex items-center gap-1 overflow-x-auto pb-1 text-xs no-scrollbar">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-0.5 mr-1 flex-shrink-0">
                <Filter className="w-3 h-3" />
                <span>Dept:</span>
              </span>
              <button
                type="button"
                onClick={() => setSelectedDept('ALL')}
                className={`px-2 py-0.5 rounded-md text-[11px] font-semibold whitespace-nowrap transition-colors flex-shrink-0 ${
                  selectedDept === 'ALL'
                    ? 'bg-medpark-500 text-white'
                    : 'bg-white text-slate-600 hover:bg-slate-200 border border-slate-200'
                }`}
              >
                All ({profiles.length})
              </button>
              {(availableDepts.length > 0 ? availableDepts : MEDPARK_DEPARTMENTS).map((dept) => {
                const count = profiles.filter((p) => p.department === dept).length;
                if (count === 0 && !availableDepts.includes(dept)) return null;
                const isSelected = selectedDept === dept;
                return (
                  <button
                    key={dept}
                    type="button"
                    onClick={() => setSelectedDept(isSelected ? 'ALL' : dept)}
                    className={`px-2 py-0.5 rounded-md text-[11px] font-semibold whitespace-nowrap transition-colors flex-shrink-0 ${
                      isSelected
                        ? 'bg-medpark-500 text-white'
                        : 'bg-white text-slate-600 hover:bg-slate-200 border border-slate-200'
                    }`}
                  >
                    {dept} ({count})
                  </button>
                );
              })}
            </div>
          </div>

          {/* Roster List */}
          <div className="max-h-48 overflow-y-auto space-y-1 divide-y divide-slate-100 bg-white border border-slate-200 rounded-lg p-1.5">
            {isLoading ? (
              <div className="text-center py-6 text-xs text-slate-400">Loading registered staff...</div>
            ) : filteredProfiles.length === 0 ? (
              <div className="text-center py-6 text-xs text-slate-400">
                No staff found matching filters.
              </div>
            ) : (
              filteredProfiles.map((p) => {
                const isSelected = selectedPersonIds.has(p.id) || selectedEmails.has(p.email.toLowerCase());
                const isEnrolled = p.state === 'enrolled';
                return (
                  <div
                    key={p.id}
                    onClick={() => handleTogglePerson(p)}
                    className={`flex items-center justify-between p-1.5 rounded-lg cursor-pointer transition-colors text-xs ${
                      isSelected ? 'bg-medpark-50/70 border border-medpark-200' : 'hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-center space-x-2 min-w-0">
                      <div
                        className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${
                          isSelected
                            ? 'bg-medpark-500 border-medpark-500 text-white'
                            : 'border-slate-300 bg-white'
                        }`}
                      >
                        {isSelected && <Check className="w-3 h-3 stroke-[3]" />}
                      </div>

                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-bold text-slate-900 truncate">
                            {p.title ? `${p.title} ` : ''}{p.person_name}
                          </span>
                          {p.department && (
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-100 text-slate-700 border border-slate-200">
                              {p.department}
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-slate-500 truncate flex items-center gap-1.5 mt-0.5">
                          <span>{p.role || 'Member'}</span>
                          {p.specialty && (
                            <>
                              <span>&middot;</span>
                              <span className="text-slate-600 font-medium">{p.specialty}</span>
                            </>
                          )}
                          {p.email && (
                            <>
                              <span>&middot;</span>
                              <span className="font-mono text-slate-400">{p.email}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center space-x-1.5 flex-shrink-0 ml-2">
                      {isEnrolled ? (
                        <span className="inline-flex items-center space-x-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <ShieldCheck className="w-3 h-3 text-emerald-600" />
                          <span>Voice Enrolled</span>
                        </span>
                      ) : (
                        <span className="text-[10px] text-slate-400 px-1 py-0.5">
                          No voiceprint
                        </span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Guest Form */}
      {showGuestForm && (
        <form
          onSubmit={handleAddGuest}
          className="p-3 bg-amber-50/60 border border-amber-200 rounded-xl space-y-2.5 shadow-inner"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-amber-900 flex items-center space-x-1.5">
              <UserPlus className="w-4 h-4 text-amber-700" />
              <span>Add Guest or External Attendee</span>
            </span>
            <button
              type="button"
              onClick={() => setShowGuestForm(false)}
              className="text-slate-400 hover:text-slate-600 p-0.5"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {guestError && (
            <div className="text-xs text-rose-700 bg-rose-50 p-1.5 rounded border border-rose-200">
              {guestError}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div>
              <label className="text-[11px] font-semibold text-slate-700 block mb-0.5">
                Full Name <span className="text-rose-600">*</span>
              </label>
              <input
                type="text"
                required
                value={guestName}
                onChange={(e) => setGuestName(e.target.value)}
                placeholder="e.g. Dr. Guest Specialist"
                className="w-full text-xs px-2.5 py-1.5 bg-white rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-500/20"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-slate-700 block mb-0.5">
                Email Address <span className="text-rose-600">*</span>
              </label>
              <input
                type="email"
                required
                value={guestEmail}
                onChange={(e) => setGuestEmail(e.target.value)}
                placeholder="guest@hospital.org"
                className="w-full text-xs px-2.5 py-1.5 bg-white rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-500/20"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-slate-700 block mb-0.5">
                Role / Organization
              </label>
              <input
                type="text"
                value={guestRole}
                onChange={(e) => setGuestRole(e.target.value)}
                placeholder="e.g. External Consultant"
                className="w-full text-xs px-2.5 py-1.5 bg-white rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-500/20"
              />
            </div>
          </div>

          <div className="flex items-center justify-end space-x-2 pt-1">
            <button
              type="button"
              onClick={() => setShowGuestForm(false)}
              className="px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-3.5 py-1 bg-amber-600 hover:bg-amber-700 text-white font-bold text-xs rounded-lg shadow-xs flex items-center space-x-1"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Confirm Guest</span>
            </button>
          </div>
        </form>
      )}

      {/* Selected Attendees Roster */}
      <div className="max-h-44 overflow-y-auto divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white p-2 space-y-1">
        {attendees.length === 0 ? (
          <div className="text-center py-4 text-xs text-slate-400 italic">
            No participants selected. Click &quot;Select Staff&quot; or &quot;+ Add Guest&quot; above.
          </div>
        ) : (
          attendees.map((att) => {
            const isGuest = !att.person_id;
            return (
              <div
                key={att.id}
                className="flex items-center justify-between text-xs py-1 px-1.5 hover:bg-slate-50 rounded-lg group"
              >
                <div className="min-w-0 flex items-center space-x-2 truncate">
                  <span className="font-bold text-slate-800 truncate">{att.name}</span>
                  {att.department && (
                    <span
                      className={`text-[10px] px-1.5 py-0.2 rounded font-medium ${
                        isGuest
                          ? 'bg-amber-50 text-amber-800 border border-amber-200'
                          : 'bg-medpark-50 text-medpark-700 border border-medpark-200'
                      }`}
                    >
                      {att.department}
                    </span>
                  )}
                  {isGuest ? (
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-100 text-slate-600">
                      Guest
                    </span>
                  ) : (
                    <span className="text-[10px] text-emerald-700 font-semibold flex items-center gap-0.5">
                      <ShieldCheck className="w-3 h-3" />
                      <span>Staff</span>
                    </span>
                  )}
                  <span className="text-slate-400 font-mono text-[11px] truncate hidden sm:inline">
                    {att.email}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={() => handleRemoveAttendee(att.id)}
                  disabled={disabled}
                  aria-label={`Remove ${att.name}`}
                  title={`Remove ${att.name}`}
                  className="flex-shrink-0 text-slate-400 hover:text-rose-600 p-1 rounded transition-colors disabled:opacity-40"
                >
                  <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
