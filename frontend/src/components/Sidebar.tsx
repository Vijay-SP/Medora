import React from 'react';
import {
  LayoutDashboard,
  Mic,
  UploadCloud,
  FileSpreadsheet,
  MailCheck,
  Settings,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Activity,
  Layers,
  Archive,
  Users,
} from 'lucide-react';
import { MedoraLogo } from './MedoraLogo';
import { Meeting } from '../types';

export type AppPage =
  | 'dashboard'
  | 'vault'
  | 'workspace'
  | 'live'
  | 'people'
  | 'deliveries'
  | 'settings';

interface NavItem {
  id: AppPage;
  label: string;
  icon: React.FC<{ className?: string }>;
  badge?: number | string;
  badgeColor?: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

interface SidebarProps {
  currentPage: AppPage;
  onNavigate: (page: AppPage) => void;
  onStartLiveMeeting: () => void;
  onUploadRecording: () => void;
  selectedMeeting: Meeting | null;
  totalMeetingsCount: number;
  pendingReviewsCount: number;
  failedDeliveriesCount?: number;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  voiceIdEnabled?: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentPage,
  onNavigate,
  onStartLiveMeeting,
  onUploadRecording,
  selectedMeeting,
  totalMeetingsCount,
  pendingReviewsCount,
  failedDeliveriesCount,
  isCollapsed,
  onToggleCollapse,
  voiceIdEnabled = false,
}) => {
  const sections: NavSection[] = [
    {
      title: 'Workspace',
      items: [
        {
          id: 'dashboard',
          label: 'Executive Dashboard',
          icon: LayoutDashboard,
        },
        {
          id: 'vault',
          label: 'Meeting Intelligence Vault',
          icon: Archive,
          badge: totalMeetingsCount,
          badgeColor: 'bg-slate-200 text-slate-700 font-semibold',
        },
        {
          id: 'live',
          label: 'Live Meeting Room',
          icon: Mic,
          badge: 'Live',
          badgeColor: 'bg-rose-100 text-rose-700 animate-pulse',
        },
      ],
    },
    {
      title: 'Management',
      items: [
        {
          id: 'people',
          label: 'People & Voices',
          icon: Users,
          badge: voiceIdEnabled ? 'Profiles' : undefined,
          badgeColor: 'bg-blue-50 text-blue-700 border border-blue-200 font-medium',
        },
        {
          id: 'deliveries',
          label: 'Email Deliveries',
          icon: MailCheck,
          badge: failedDeliveriesCount && failedDeliveriesCount > 0 ? `${failedDeliveriesCount} failed` : undefined,
          badgeColor: 'bg-rose-100 text-rose-800 font-semibold',
        },
        {
          id: 'settings',
          label: 'System & Air-Gap',
          icon: Settings,
        },
      ],
    },
  ];

  return (
    <aside
      aria-label="Application navigation"
      className={`bg-white border-r border-slate-200 sticky top-0 h-screen flex-shrink-0 flex flex-col justify-between transition-all duration-300 z-30 select-none ${
        isCollapsed ? 'w-20' : 'w-64 sm:w-72'
      }`}
    >
      {/* Top Header & Branding */}
      <div className="flex-1 min-h-0 flex flex-col overflow-y-auto">
        <div className="h-16 border-b border-slate-200 flex items-center justify-between px-4 flex-shrink-0">
          {!isCollapsed ? (
            <div className="flex items-center space-x-2 overflow-hidden">
              <MedoraLogo size="sm" showTagline={false} />
            </div>
          ) : (
            <div className="mx-auto">
              <MedoraLogo size="sm" showTagline={false} />
            </div>
          )}
          <button
            onClick={onToggleCollapse}
            aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors hidden sm:flex"
            title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>

        {/* Primary Intake Buttons: Two Clear Options */}
        <div className="p-3 space-y-2 flex-shrink-0">
          {/* Option 1: Start Live Meeting */}
          <button
            onClick={onStartLiveMeeting}
            title="Start Live Meeting (Conference Room Mic)"
            className={`w-full flex items-center justify-center space-x-2.5 px-3.5 py-2.5 rounded-xl font-bold text-xs text-white shadow-sm transition-all focus:outline-none focus:ring-2 focus:ring-rose-500/20 active:scale-[0.98] ${
              currentPage === 'live'
                ? 'bg-rose-700 ring-2 ring-rose-500 ring-offset-1'
                : 'bg-gradient-to-r from-rose-600 to-rose-700 hover:from-rose-700 hover:to-rose-800'
            }`}
          >
            <div className="relative flex items-center justify-center">
              <Mic className="w-4 h-4 flex-shrink-0" />
              <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-amber-300 animate-ping" />
            </div>
            {!isCollapsed && <span className="truncate">Start Live Meeting</span>}
          </button>

          {/* Option 2: Upload Recorded Meeting */}
          <button
            onClick={onUploadRecording}
            title="Upload Recorded Audio File"
            className="w-full flex items-center justify-center space-x-2.5 px-3.5 py-2.5 rounded-xl font-bold text-xs bg-slate-100 hover:bg-slate-200/80 text-slate-800 border border-slate-200/80 transition-all focus:outline-none focus:ring-2 focus:ring-medpark-500/20 active:scale-[0.98]"
          >
            <UploadCloud className="w-4 h-4 text-slate-600 flex-shrink-0" />
            {!isCollapsed && <span className="truncate">Upload Recording</span>}
          </button>
        </div>

        {/* Navigation Sections */}
        <nav className="px-3 py-2 space-y-4">
          {sections.map((section, sIdx) => (
            <div key={section.title} className="space-y-1">
              {/* Section Header */}
              {!isCollapsed ? (
                <div className="px-2 pt-1 pb-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    {section.title}
                  </span>
                </div>
              ) : sIdx > 0 ? (
                <div className="my-2 border-t border-slate-200/80" />
              ) : null}

              {/* Items in Section */}
              <div className="space-y-1">
                {section.items.map((item) => {
                  const Icon = item.icon;
                  const isActive = currentPage === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => onNavigate(item.id)}
                      title={item.label}
                      aria-current={isActive ? 'page' : undefined}
                      className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-semibold transition-all group ${
                        isActive
                          ? 'bg-medpark-50 text-medpark-700 border border-medpark-200/70 shadow-xs'
                          : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/80'
                      }`}
                    >
                      <div className={`flex items-center space-x-3 ${isCollapsed ? 'mx-auto' : ''}`}>
                        <Icon
                          className={`w-4 h-4 flex-shrink-0 transition-colors ${
                            isActive ? 'text-medpark-600' : 'text-slate-400 group-hover:text-slate-600'
                          }`}
                        />
                        {!isCollapsed && <span className="truncate">{item.label}</span>}
                      </div>

                      {!isCollapsed && item.badge !== undefined && (
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                            item.badgeColor || 'bg-slate-100 text-slate-600'
                          }`}
                        >
                          {item.badge}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </div>

      {/* Bottom Section: Active Meeting & Offline Badge */}
      <div className="p-3 border-t border-slate-200 space-y-2 flex-shrink-0">
        {/* Active Session Indicator */}
        {!isCollapsed && selectedMeeting && (
          <div
            onClick={() => onNavigate('workspace')}
            role="button"
            tabIndex={0}
            title="Click to view active meeting in workspace"
            className={`p-2.5 rounded-xl cursor-pointer transition-colors ${
              currentPage === 'workspace'
                ? 'bg-medpark-50 border border-medpark-300 ring-1 ring-medpark-400/50 shadow-xs'
                : 'bg-slate-50 hover:bg-slate-100 border border-slate-200'
            }`}
          >
            <div className="flex items-center justify-between text-[10px] text-slate-500 font-semibold mb-1">
              <span className="flex items-center space-x-1">
                <Layers className={`w-3 h-3 ${currentPage === 'workspace' ? 'text-medpark-700' : 'text-medpark-600'}`} />
                <span className={currentPage === 'workspace' ? 'font-bold text-medpark-800' : ''}>Active Session</span>
              </span>
              <span className="uppercase text-medpark-600 font-bold">
                {currentPage === 'workspace' ? 'Viewing' : 'Open'}
              </span>
            </div>
            <p className="text-xs font-bold text-slate-800 truncate" title={selectedMeeting.title}>
              {selectedMeeting.title}
            </p>
            <div className="mt-1 flex items-center space-x-2 text-[10px] text-slate-500">
              <span className="capitalize">{selectedMeeting.meeting_type}</span>
              <span>•</span>
              <span className="capitalize font-mono">{selectedMeeting.review_status.replace('_', ' ')}</span>
            </div>
          </div>
        )}

        {/* Air-Gapped Trust Stamp */}
        <div className={`flex items-center text-xs text-emerald-800 bg-emerald-50/80 border border-emerald-200/80 rounded-xl p-2.5 ${
          isCollapsed ? 'justify-center' : 'space-x-2'
        }`}>
          <ShieldCheck className="w-4 h-4 text-emerald-600 flex-shrink-0" />
          {!isCollapsed && (
            <div className="min-w-0">
              <p className="text-[11px] font-bold text-emerald-900 leading-tight">100% Offline AI</p>
              <p className="text-[10px] text-emerald-700 leading-tight truncate">Air-Gapped Hospital Data</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};
