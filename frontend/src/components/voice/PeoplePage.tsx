import React, { useEffect, useRef, useState } from 'react';
import {
  Users,
  Plus,
  RefreshCw,
  AlertTriangle,
  Trash2,
  ShieldOff,
  Loader2,
  X,
  Cpu,
  ChevronLeft,
  Search,
  Building2,
  Filter,
  Pencil,
} from 'lucide-react';
import { VoiceProfile, VoiceStatus } from '../../types';
import { apiClient } from '../../api/client';
import { useToast } from '../Toast';
import { VoiceProfileCard } from './VoiceProfileCard';
import { EnrollmentDrawer } from './EnrollmentDrawer';
import { ConsentNotice } from './ConsentNotice';

interface PeoplePageProps {
  onBack?: () => void;
}

// ---------------------------------------------------------------------------------------------
// Confirmation dialog: says exactly what a destructive action removes and what it keeps.
// Focus lands on Cancel, Tab is trapped, Escape cancels, focus is restored on close.
// ---------------------------------------------------------------------------------------------
interface ConfirmDialogProps {
  title: string;
  intro: React.ReactNode;
  removed: string[];
  kept: string[];
  // Consequences that are neither removed now nor kept unchanged (e.g. deferred clean-up).
  note?: React.ReactNode;
  confirmLabel: string;
  tone: 'rose' | 'amber';
  Icon: React.FC<{ className?: string }>;
  isBusy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  title,
  intro,
  removed,
  kept,
  note,
  confirmLabel,
  tone,
  Icon,
  isBusy,
  onCancel,
  onConfirm,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useRef(`confirm-${Math.random().toString(36).slice(2, 8)}`).current;

  useEffect(() => {
    const panel = panelRef.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onCancel();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      const focusables = Array.from(
        panel.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex]:not([tabindex="-1"])')
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
  }, [onCancel]);

  const toneText = tone === 'rose' ? 'text-rose-600' : 'text-amber-700';
  const confirmClass =
    tone === 'rose' ? 'bg-rose-600 hover:bg-rose-700' : 'bg-amber-600 hover:bg-amber-700';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="bg-white rounded-2xl shadow-xl border border-slate-200 max-w-md w-full p-6 space-y-4 focus:outline-none"
      >
        <div className={`flex items-center space-x-3 ${toneText}`}>
          <Icon className="w-6 h-6" />
          <h3 id={titleId} className="font-bold text-base text-slate-900">
            {title}
          </h3>
        </div>

        <div className="space-y-3 text-xs text-slate-600 leading-relaxed">
          <p>{intro}</p>
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-3">
            <p className="text-[11px] font-bold uppercase tracking-wider text-rose-700">Removed now</p>
            <ul className="mt-1 space-y-1 text-xs text-rose-800 font-medium list-disc list-inside">
              {removed.map((r, idx) => (
                <li key={idx}>{r}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-600">Kept</p>
            <ul className="mt-1 space-y-1 text-xs text-slate-700 font-medium list-disc list-inside">
              {kept.map((k, idx) => (
                <li key={idx}>{k}</li>
              ))}
            </ul>
          </div>
          {note && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-amber-700">Cleared later</p>
              <p className="mt-1 text-xs text-amber-900 font-medium">{note}</p>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end space-x-3 pt-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={isBusy}
            className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isBusy}
            className={`inline-flex items-center space-x-1.5 px-4 py-2 text-xs font-bold text-white rounded-lg shadow-sm transition-colors disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-slate-700 ${confirmClass}`}
          >
            {isBusy && <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />}
            <span>{confirmLabel}</span>
          </button>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------------------------
// Add-person dialog
// ---------------------------------------------------------------------------------------------
export const MEDPARK_DEPARTMENTS = [
  'Cardiology',
  'Cardiovascular Surgery',
  'Intensive Care & Anesthesiology (ATI)',
  'General Surgery',
  'Emergency Care (UPU)',
  'Neurology & Neurosurgery',
  'Oncology',
  'Pediatrics & Neonatology',
  'Obstetrics & Gynecology',
  'Radiology & Medical Imaging',
  'Laboratory & Pathology',
  'Hospital Administration',
  'Pharmacy',
];

const TITLE_OPTIONS = [
  { value: '', label: 'None' },
  { value: 'Dr.', label: 'Dr.' },
  { value: 'Prof. Dr.', label: 'Prof. Dr.' },
  { value: 'Conf. Dr.', label: 'Conf. Dr.' },
  { value: 'Dr. Șt. Med.', label: 'Dr. Șt. Med.' },
  { value: 'Medic Rezident', label: 'Medic Rezident' },
  { value: 'Asist. Univ.', label: 'Asist. Univ.' },
  { value: 'Asistent Medical', label: 'Asistent Medical' },
  { value: 'Dna.', label: 'Dna.' },
  { value: 'Dl.', label: 'Dl.' },
];

const LANGUAGE_OPTIONS = [
  { code: 'ro', label: 'Romanian (Română)' },
  { code: 'ru', label: 'Russian (Русский)' },
  { code: 'en', label: 'English' },
];

interface AddPersonDialogProps {
  onCancel: () => void;
  onCreated: (profile: VoiceProfile) => void;
}

const AddPersonDialog: React.FC<AddPersonDialogProps> = ({ onCancel, onCreated }) => {
  const [title, setTitle] = useState('Dr.');
  const [name, setName] = useState('');
  const [department, setDepartment] = useState('Cardiology');
  const [customDepartment, setCustomDepartment] = useState('');
  const [role, setRole] = useState('Member');
  const [specialty, setSpecialty] = useState('');
  const [primaryLanguage, setPrimaryLanguage] = useState('ro');
  const [email, setEmail] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const panel = panelRef.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const initial = panel?.querySelector<HTMLElement>('[data-autofocus]') || panel;
    initial?.focus();

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onCancel();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      const focusables = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
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
  }, [onCancel]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setFormError('Full name is required.');
      return;
    }
    const resolvedDept = department === 'CUSTOM' ? customDepartment.trim() : department.trim();
    if (department === 'CUSTOM' && !resolvedDept) {
      setFormError('Please enter a department name.');
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    try {
      const created = await apiClient.createVoiceProfile({
        person_name: name.trim(),
        title: title || undefined,
        role: role.trim() || 'Member',
        department: resolvedDept || undefined,
        specialty: specialty.trim() || undefined,
        primary_language: primaryLanguage || 'ro',
        email: email.trim(),
      });
      onCreated(created);
    } catch (err: any) {
      setFormError(err?.message || 'The person could not be created.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4 overflow-y-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-2xl shadow-xl border border-slate-200 max-w-lg w-full overflow-hidden my-8"
      >
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="add-person-title"
          tabIndex={-1}
          className="focus:outline-none"
        >
          <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <div className="w-7 h-7 rounded-lg bg-medpark-500 text-white flex items-center justify-center">
                <Plus className="w-4 h-4" aria-hidden="true" />
              </div>
              <h3 id="add-person-title" className="font-bold text-slate-900 text-sm">
                Register New Person &amp; Clinical Context
              </h3>
            </div>
            <button
              type="button"
              onClick={onCancel}
              aria-label="Close add person"
              className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>

          <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
            <p className="text-xs text-slate-600 leading-relaxed">
              Register medical staff with clinical context (department, specialty, language). Voice
              biometrics are enrolled afterwards by the person after giving consent.
            </p>
            {formError && (
              <p role="alert" className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2">
                {formError}
              </p>
            )}

            {/* Title + Name Row */}
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5 col-span-1">
                <label htmlFor="person-title" className="text-xs font-semibold text-slate-700">
                  Title
                </label>
                <select
                  id="person-title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full text-xs px-2.5 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                >
                  {TITLE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5 col-span-2">
                <label htmlFor="person-name" className="text-xs font-semibold text-slate-700">
                  Full name <span className="text-rose-600" aria-hidden="true">*</span>
                </label>
                <input
                  id="person-name"
                  type="text"
                  required
                  aria-required="true"
                  data-autofocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  placeholder="e.g., Elena Ceban"
                />
              </div>
            </div>

            {/* Department + Custom */}
            <div className="space-y-1.5">
              <label htmlFor="person-department" className="text-xs font-semibold text-slate-700">
                Department
              </label>
              <select
                id="person-department"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              >
                {MEDPARK_DEPARTMENTS.map((dept) => (
                  <option key={dept} value={dept}>
                    {dept}
                  </option>
                ))}
                <option value="CUSTOM">+ Other / Custom department...</option>
              </select>
              {department === 'CUSTOM' && (
                <input
                  type="text"
                  required
                  value={customDepartment}
                  onChange={(e) => setCustomDepartment(e.target.value)}
                  placeholder="Enter department name..."
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20 mt-1.5"
                />
              )}
            </div>

            {/* Role & Specialty */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="person-role" className="text-xs font-semibold text-slate-700">
                  Clinical Role
                </label>
                <input
                  id="person-role"
                  type="text"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  placeholder="e.g., Head of Dept, Consultant"
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="person-specialty" className="text-xs font-semibold text-slate-700">
                  Specialty / Sub-specialty
                </label>
                <input
                  id="person-specialty"
                  type="text"
                  value={specialty}
                  onChange={(e) => setSpecialty(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  placeholder="e.g., Interventional Cardiology"
                />
              </div>
            </div>

            {/* Primary Language & Email */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="person-language" className="text-xs font-semibold text-slate-700">
                  Primary Meeting Language
                </label>
                <select
                  id="person-language"
                  value={primaryLanguage}
                  onChange={(e) => setPrimaryLanguage(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                >
                  {LANGUAGE_OPTIONS.map((lang) => (
                    <option key={lang.code} value={lang.code}>
                      {lang.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="person-email" className="text-xs font-semibold text-slate-700">
                  Internal Hospital Email
                </label>
                <input
                  id="person-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  placeholder="name@medpark.md"
                />
              </div>
            </div>
          </div>

          <div className="p-4 bg-slate-50 border-t border-slate-200 flex items-center justify-end space-x-2">
            <button
              type="button"
              onClick={onCancel}
              disabled={isSubmitting}
              className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center space-x-1.5 px-4 py-2 text-xs font-bold bg-medpark-500 hover:bg-medpark-600 text-white rounded-lg shadow-xs transition-colors disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 focus-visible:ring-offset-1"
            >
              {isSubmitting && <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />}
              <span>Register person</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};

// ---------------------------------------------------------------------------------------------
// Edit-person dialog
// ---------------------------------------------------------------------------------------------
interface EditPersonDialogProps {
  profile: VoiceProfile;
  onCancel: () => void;
  onUpdated: (profile: VoiceProfile) => void;
}

const EditPersonDialog: React.FC<EditPersonDialogProps> = ({ profile, onCancel, onUpdated }) => {
  const isKnownDept = profile.department ? MEDPARK_DEPARTMENTS.includes(profile.department) : false;
  const [title, setTitle] = useState(profile.title || '');
  const [name, setName] = useState(profile.person_name || '');
  const [department, setDepartment] = useState(
    profile.department
      ? isKnownDept
        ? profile.department
        : 'CUSTOM'
      : 'Cardiology'
  );
  const [customDepartment, setCustomDepartment] = useState(
    profile.department && !isKnownDept ? profile.department : ''
  );
  const [role, setRole] = useState(profile.role || 'Member');
  const [specialty, setSpecialty] = useState(profile.specialty || '');
  const [primaryLanguage, setPrimaryLanguage] = useState(profile.primary_language || 'ro');
  const [email, setEmail] = useState(profile.email || '');
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const panel = panelRef.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const initial = panel?.querySelector<HTMLElement>('[data-autofocus]') || panel;
    initial?.focus();

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onCancel();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      const focusables = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
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
  }, [onCancel]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setFormError('Full name is required.');
      return;
    }
    const resolvedDept = department === 'CUSTOM' ? customDepartment.trim() : department.trim();
    if (department === 'CUSTOM' && !resolvedDept) {
      setFormError('Please enter a department name.');
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    try {
      const updated = await apiClient.updateVoiceProfile(profile.id, {
        person_name: name.trim(),
        title: title || undefined,
        role: role.trim() || 'Member',
        department: resolvedDept || undefined,
        specialty: specialty.trim() || undefined,
        primary_language: primaryLanguage || 'ro',
        email: email.trim(),
      });
      onUpdated(updated);
    } catch (err: any) {
      setFormError(err?.message || 'The person details could not be updated.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4 overflow-y-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-2xl shadow-xl border border-slate-200 max-w-lg w-full overflow-hidden my-8"
      >
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-person-title"
          tabIndex={-1}
          className="focus:outline-none"
        >
          <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <div className="w-7 h-7 rounded-lg bg-medpark-500 text-white flex items-center justify-center">
                <Pencil className="w-4 h-4" aria-hidden="true" />
              </div>
              <h3 id="edit-person-title" className="font-bold text-slate-900 text-sm">
                Edit Person Details &amp; Clinical Context
              </h3>
            </div>
            <button
              type="button"
              onClick={onCancel}
              aria-label="Close edit person"
              className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>

          <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
            <p className="text-xs text-slate-600 leading-relaxed">
              Update personal details and clinical context. Voice biometrics, consent records, and past meeting
              confirmations remain completely preserved.
            </p>
            {formError && (
              <p role="alert" className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2">
                {formError}
              </p>
            )}

            {/* Title + Name Row */}
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5 col-span-1">
                <label htmlFor="edit-person-title-select" className="text-xs font-semibold text-slate-700">
                  Title
                </label>
                <select
                  id="edit-person-title-select"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full text-xs px-2.5 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                >
                  {TITLE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5 col-span-2">
                <label htmlFor="edit-person-name" className="text-xs font-semibold text-slate-700">
                  Full name <span className="text-rose-600" aria-hidden="true">*</span>
                </label>
                <input
                  id="edit-person-name"
                  type="text"
                  required
                  aria-required="true"
                  data-autofocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  placeholder="e.g., Elena Ceban"
                />
              </div>
            </div>

            {/* Department + Custom */}
            <div className="space-y-1.5">
              <label htmlFor="edit-person-department" className="text-xs font-semibold text-slate-700">
                Department
              </label>
              <select
                id="edit-person-department"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              >
                {MEDPARK_DEPARTMENTS.map((dept) => (
                  <option key={dept} value={dept}>
                    {dept}
                  </option>
                ))}
                <option value="CUSTOM">+ Other / Custom department...</option>
              </select>
              {department === 'CUSTOM' && (
                <input
                  type="text"
                  required
                  value={customDepartment}
                  onChange={(e) => setCustomDepartment(e.target.value)}
                  placeholder="Enter department name..."
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20 mt-1.5"
                />
              )}
            </div>

            {/* Role & Specialty */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="edit-person-role" className="text-xs font-semibold text-slate-700">
                  Clinical Role
                </label>
                <input
                  id="edit-person-role"
                  type="text"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  placeholder="e.g., Head of Dept, Consultant"
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="edit-person-specialty" className="text-xs font-semibold text-slate-700">
                  Specialty / Sub-specialty
                </label>
                <input
                  id="edit-person-specialty"
                  type="text"
                  value={specialty}
                  onChange={(e) => setSpecialty(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  placeholder="e.g., Interventional Cardiology"
                />
              </div>
            </div>

            {/* Primary Language & Email */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="edit-person-language" className="text-xs font-semibold text-slate-700">
                  Primary Meeting Language
                </label>
                <select
                  id="edit-person-language"
                  value={primaryLanguage}
                  onChange={(e) => setPrimaryLanguage(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                >
                  {LANGUAGE_OPTIONS.map((lang) => (
                    <option key={lang.code} value={lang.code}>
                      {lang.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="edit-person-email" className="text-xs font-semibold text-slate-700">
                  Internal Hospital Email
                </label>
                <input
                  id="edit-person-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
                  placeholder="name@medpark.md"
                />
              </div>
            </div>
          </div>

          <div className="p-4 bg-slate-50 border-t border-slate-200 flex items-center justify-end space-x-2">
            <button
              type="button"
              onClick={onCancel}
              disabled={isSubmitting}
              className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center space-x-1.5 px-4 py-2 text-xs font-bold bg-medpark-500 hover:bg-medpark-600 text-white rounded-lg shadow-xs transition-colors disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 focus-visible:ring-offset-1"
            >
              {isSubmitting && <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />}
              <span>Save changes</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};

// ---------------------------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------------------------
type PendingAction =
  | { kind: 'delete'; profile: VoiceProfile }
  | { kind: 'withdraw'; profile: VoiceProfile }
  | { kind: 'wipe'; profile: VoiceProfile };

export const PeoplePage: React.FC<PeoplePageProps> = ({ onBack }) => {
  const { showToast } = useToast();
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<VoiceProfile | null>(null);
  const [enrolling, setEnrolling] = useState<VoiceProfile | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [selectedDepartment, setSelectedDepartment] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const availableDepartments = React.useMemo(() => {
    const deps = new Set<string>();
    profiles.forEach((p) => {
      if (p.department) deps.add(p.department);
    });
    return Array.from(deps).sort();
  }, [profiles]);

  const filteredProfiles = React.useMemo(() => {
    return profiles.filter((p) => {
      if (selectedDepartment !== 'ALL' && p.department !== selectedDepartment) {
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
  }, [profiles, selectedDepartment, searchQuery]);

  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [people, st] = await Promise.all([
        apiClient.listVoiceProfiles(),
        apiClient.getVoiceStatus().catch(() => null),
      ]);
      setProfiles(people);
      setStatus(st);
    } catch (err: any) {
      console.error('Failed to load voice profiles:', err);
      setProfiles([]);
      setError(err?.message || 'Could not load people.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const replaceProfile = (updated: VoiceProfile) => {
    setProfiles((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    setEnrolling((prev) => (prev && prev.id === updated.id ? updated : prev));
  };

  const refreshStatus = () => {
    apiClient
      .getVoiceStatus()
      .then(setStatus)
      .catch(() => undefined);
  };

  const recordingBlockedReason: string | null =
    status && !status.enabled
      ? 'Voice identification is disabled on this server.'
      : status && !status.embedder_available
        ? 'The speaker embedder model is not available on this server; samples cannot be assessed.'
        : null;

  const handleConfirmPending = async () => {
    if (!pending) return;
    const { kind, profile } = pending;
    setIsActing(true);
    try {
      if (kind === 'delete') {
        await apiClient.deleteVoiceProfile(profile.id);
        setProfiles((prev) => prev.filter((p) => p.id !== profile.id));
        showToast('Person deleted', `${profile.person_name}: voiceprint and samples removed.`);
      } else if (kind === 'withdraw') {
        const updated = await apiClient.setVoiceConsent(profile.id, false);
        replaceProfile(updated);
        showToast('Consent withdrawn', `${profile.person_name}: voiceprint and samples removed.`, 'warning');
      } else {
        await apiClient.wipeVoiceSamples(profile.id);
        const refreshed = await apiClient.getVoiceProfile(profile.id);
        replaceProfile(refreshed);
        showToast('Samples removed', `${profile.person_name} can now re-enroll from scratch.`, 'warning');
      }
      setPending(null);
      refreshStatus();
    } catch (err: any) {
      showToast('Action failed', err?.message || 'Server error', 'error');
    } finally {
      setIsActing(false);
    }
  };

  const counts = {
    enrolled: profiles.filter((p) => p.state === 'enrolled').length,
    notEnrolled: profiles.filter((p) => p.state === 'not_enrolled').length,
    needsReenrollment: profiles.filter((p) => p.state === 'needs_reenrollment').length,
  };

  return (
    <div className="w-full space-y-6">
      {/* Header */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xs flex flex-col lg:flex-row lg:items-start justify-between gap-4">
        <div className="space-y-1.5 min-w-0">
          <div className="flex items-center space-x-2">
            {onBack && (
              <button
                type="button"
                onClick={onBack}
                className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
              >
                <ChevronLeft className="w-4 h-4" aria-hidden="true" />
                <span>Back</span>
              </button>
            )}
            <h2 className="text-xl font-black text-slate-900 tracking-tight flex items-center space-x-2">
              <Users className="w-5 h-5 text-medpark-600" aria-hidden="true" />
              <span>People &amp; Voices</span>
            </h2>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed max-w-2xl">
            Enrolled voices let the system <em>suggest</em> who is speaking in a recording. A suggestion
            reaches a document only after a human reviewer confirms it on the meeting's Speakers tab.
            Each person enrolls their own voice, here, after giving consent.
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] font-semibold">
            <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 tabular-nums">
              {counts.enrolled} enrolled
            </span>
            <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200 tabular-nums">
              {counts.notEnrolled} not enrolled
            </span>
            {counts.needsReenrollment > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-amber-50 text-amber-900 border border-amber-300 tabular-nums">
                {counts.needsReenrollment} need re-enrollment
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2 lg:items-end flex-shrink-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={load}
              disabled={isLoading}
              aria-label="Refresh people"
              title="Refresh"
              className="p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => setIsAddOpen(true)}
              className="inline-flex items-center space-x-1.5 px-3.5 py-2 bg-medpark-500 hover:bg-medpark-600 text-white text-xs font-bold rounded-lg shadow-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500 focus-visible:ring-offset-1"
            >
              <Plus className="w-4 h-4" aria-hidden="true" />
              <span>Add person</span>
            </button>
          </div>

          {/* Embedder status, read from the server: never claim availability the backend did not report. */}
          <div
            role="status"
            className={`inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border ${
              !status
                ? 'bg-slate-50 text-slate-500 border-slate-200'
                : status.enabled && status.embedder_available
                  ? 'bg-slate-50 text-slate-700 border-slate-200'
                  : 'bg-amber-50 text-amber-900 border-amber-300'
            }`}
            title={status?.space_id ? `Embedding space ${status.space_id}` : 'Embedder status not reported'}
          >
            <Cpu
              className={`w-3.5 h-3.5 ${
                status?.enabled && status?.embedder_available ? 'text-emerald-500' : 'text-amber-500'
              }`}
              aria-hidden="true"
            />
            <span className="font-mono">{status?.model || 'speaker embedder'}</span>
            <span className="font-medium">
              {!status
                ? 'status unknown'
                : !status.enabled
                  ? 'disabled'
                  : status.embedder_available
                    ? `ready · ${status.dim ?? '?'}-d`
                    : 'model missing'}
            </span>
          </div>
        </div>
      </div>

      {recordingBlockedReason && (
        <div role="alert" className="p-4 rounded-2xl border border-amber-300 bg-amber-50 text-amber-900 flex items-start gap-3 shadow-xs">
          <AlertTriangle className="w-5 h-5 text-amber-700 flex-shrink-0" aria-hidden="true" />
          <p className="text-xs font-semibold leading-relaxed">{recordingBlockedReason} People can still be added and deleted.</p>
        </div>
      )}

      {error && (
        <div role="alert" className="p-4 rounded-2xl border border-rose-200 bg-rose-50 text-rose-800 flex items-start gap-3 shadow-xs">
          <AlertTriangle className="w-5 h-5 text-rose-600 flex-shrink-0" aria-hidden="true" />
          <div className="text-xs space-y-1">
            <p className="font-bold">People could not be loaded</p>
            <p className="leading-relaxed">{error} The list below is not a confirmed empty list.</p>
          </div>
        </div>
      )}

      {/* Search and Department Filter Toolbar */}
      {profiles.length > 0 && (
        <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-xs space-y-3">
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="relative flex-1 max-w-md">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search staff by name, role, department or specialty..."
                className="w-full pl-9 pr-8 py-2 text-xs rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-0.5 rounded-full"
                  aria-label="Clear search"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            <div className="text-xs text-slate-500 font-medium flex items-center gap-1.5 self-end sm:self-auto">
              <span>Showing</span>
              <strong className="text-slate-800 font-bold">{filteredProfiles.length}</strong>
              <span>of {profiles.length} staff</span>
            </div>
          </div>

          {/* Department Pills */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 pt-1 no-scrollbar text-xs">
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 mr-1 flex-shrink-0">
              <Filter className="w-3.5 h-3.5" />
              <span>Dept:</span>
            </span>

            <button
              type="button"
              onClick={() => setSelectedDepartment('ALL')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors flex-shrink-0 flex items-center space-x-1.5 ${
                selectedDepartment === 'ALL'
                  ? 'bg-medpark-500 text-white shadow-xs'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              <span>All Staff</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold ${
                selectedDepartment === 'ALL' ? 'bg-medpark-600 text-white' : 'bg-slate-200 text-slate-700'
              }`}>
                {profiles.length}
              </span>
            </button>

            {availableDepartments.map((dept) => {
              const count = profiles.filter((p) => p.department === dept).length;
              const isSelected = selectedDepartment === dept;
              return (
                <button
                  key={dept}
                  type="button"
                  onClick={() => setSelectedDepartment(isSelected ? 'ALL' : dept)}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors flex-shrink-0 flex items-center space-x-1.5 ${
                    isSelected
                      ? 'bg-medpark-500 text-white shadow-xs'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  <span>{dept}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold ${
                    isSelected ? 'bg-medpark-600 text-white' : 'bg-slate-200 text-slate-700'
                  }`}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Grid */}
      <section aria-label="People" aria-busy={isLoading}>
        {isLoading ? (
          <div role="status" className="text-center py-16 text-xs text-slate-400">
            Loading people...
          </div>
        ) : profiles.length === 0 && !error ? (
          <div className="bg-white rounded-2xl border border-slate-200 p-10 shadow-xs text-center space-y-3">
            <Users className="w-8 h-8 text-slate-300 mx-auto" aria-hidden="true" />
            <h3 className="text-sm font-bold text-slate-900">No people yet</h3>
            <p className="text-xs text-slate-600 max-w-md mx-auto leading-relaxed">
              Add the staff who attend recorded meetings. Each person then enrolls their own voice
              after reading the consent statement.
            </p>
            <div className="max-w-xl mx-auto text-left">
              <ConsentNotice variant="compact" />
            </div>
          </div>
        ) : filteredProfiles.length === 0 ? (
          <div className="bg-white rounded-2xl border border-slate-200 p-10 shadow-xs text-center space-y-3">
            <Building2 className="w-8 h-8 text-slate-300 mx-auto" aria-hidden="true" />
            <h4 className="text-sm font-bold text-slate-800">No staff found matching filters</h4>
            <p className="text-xs text-slate-500">
              Try clearing the search query or selecting &quot;All Staff&quot;.
            </p>
            <button
              type="button"
              onClick={() => {
                setSelectedDepartment('ALL');
                setSearchQuery('');
              }}
              className="mt-2 inline-flex items-center px-3 py-1.5 text-xs font-bold text-medpark-600 bg-medpark-50 hover:bg-medpark-100 rounded-lg transition-colors"
            >
              Reset filters
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredProfiles.map((p) => (
              <VoiceProfileCard
                key={p.id}
                profile={p}
                recordingBlockedReason={recordingBlockedReason}
                onEnroll={(profile) => setEnrolling(profile)}
                onEdit={(profile) => setEditingProfile(profile)}
                onWipeSamples={(profile) => setPending({ kind: 'wipe', profile })}
                onWithdrawConsent={(profile) => setPending({ kind: 'withdraw', profile })}
                onDelete={(profile) => setPending({ kind: 'delete', profile })}
              />
            ))}
          </div>
        )}
      </section>

      {isAddOpen && (
        <AddPersonDialog
          onCancel={() => setIsAddOpen(false)}
          onCreated={(created) => {
            setProfiles((prev) => [created, ...prev]);
            setIsAddOpen(false);
            showToast('Person added', `${created.person_name} can now give consent and enroll.`);
            refreshStatus();
          }}
        />
      )}

      {editingProfile && (
        <EditPersonDialog
          profile={editingProfile}
          onCancel={() => setEditingProfile(null)}
          onUpdated={(updated) => {
            replaceProfile(updated);
            setEditingProfile(null);
            showToast('Person updated', `${updated.person_name}: details saved.`);
            refreshStatus();
          }}
        />
      )}

      <EnrollmentDrawer
        profile={enrolling}
        isOpen={enrolling !== null}
        onClose={() => {
          setEnrolling(null);
          refreshStatus();
        }}
        onProfileChange={replaceProfile}
      />

      {pending?.kind === 'delete' && (
        <ConfirmDialog
          title="Delete this person?"
          Icon={Trash2}
          tone="rose"
          isBusy={isActing}
          intro={
            <>
              This permanently deletes <strong>{pending.profile.person_name}</strong> from People &amp;
              Voices.
            </>
          }
          removed={[
            'Their voiceprint (the numeric voice template)',
            'All stored enrollment samples',
            'Their consent record',
          ]}
          kept={[
            'Names a reviewer already confirmed on past meetings: those are signed snapshots and stay as they are',
            'The audit trail of past speaker decisions',
          ]}
          note={
            <>
              Pending &quot;Is this {pending.profile.person_name}?&quot; suggestions on meetings are not
              deleted now. They can no longer be confirmed (the server refuses a deleted person and the
              Speakers panel disables &quot;Yes&quot;), and each meeting drops them the next time it is
              re-matched.
            </>
          }
          confirmLabel="Delete permanently"
          onCancel={() => setPending(null)}
          onConfirm={handleConfirmPending}
        />
      )}

      {pending?.kind === 'withdraw' && (
        <ConfirmDialog
          title="Withdraw consent?"
          Icon={ShieldOff}
          tone="amber"
          isBusy={isActing}
          intro={
            <>
              <strong>{pending.profile.person_name}</strong> stays in the list, but nothing biometric
              is kept and no new suggestions will be made for them.
            </>
          }
          removed={[
            'Their voiceprint (the numeric voice template)',
            'All stored enrollment samples',
          ]}
          kept={[
            'The person entry (name, role, email), marked as consent withdrawn',
            'Names a reviewer already confirmed on past meetings: those are signed snapshots and stay as they are',
          ]}
          note={
            <>
              Pending &quot;Is this {pending.profile.person_name}?&quot; suggestions on meetings are not
              deleted now. The Speakers panel stops offering &quot;Yes&quot; for a person without an
              enrolled voice, and each meeting drops them the next time it is re-matched.
            </>
          }
          confirmLabel="Withdraw consent"
          onCancel={() => setPending(null)}
          onConfirm={handleConfirmPending}
        />
      )}

      {pending?.kind === 'wipe' && (
        <ConfirmDialog
          title="Re-enroll from scratch?"
          Icon={RefreshCw}
          tone="amber"
          isBusy={isActing}
          intro={
            <>
              <strong>{pending.profile.person_name}</strong> will need to record new samples before
              their name can be suggested again.
            </>
          }
          removed={['Their current voiceprint', 'All stored enrollment samples']}
          kept={[
            'The person entry and their consent',
            'Names a reviewer already confirmed on past meetings',
          ]}
          confirmLabel="Remove samples"
          onCancel={() => setPending(null)}
          onConfirm={handleConfirmPending}
        />
      )}
    </div>
  );
};
