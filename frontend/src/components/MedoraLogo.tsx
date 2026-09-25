import React from 'react';

interface MedoraLogoProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  showTagline?: boolean;
  variant?: 'full' | 'icon-only';
  className?: string;
}

export const MedoraLogo: React.FC<MedoraLogoProps> = ({
  size = 'md',
  showTagline = false,
  variant = 'full',
  className = '',
}) => {
  // Sizing definitions
  const dimensions = {
    sm: { icon: 28, text: 'text-base', tagline: 'text-[9px]' },
    md: { icon: 38, text: 'text-xl', tagline: 'text-[11px]' },
    lg: { icon: 48, text: 'text-2xl', tagline: 'text-xs' },
    xl: { icon: 64, text: 'text-3xl', tagline: 'text-sm' },
  }[size];

  return (
    <div className={`flex items-center space-x-3 select-none ${className}`}>
      {/* Aurora Medical Icon */}
      <div className="relative flex-shrink-0 flex items-center justify-center">
        {/* Ambient Aurora Glow Backdrop */}
        <div
          className="absolute -inset-1 rounded-2xl bg-gradient-to-tr from-cyan-500/25 via-teal-400/20 to-emerald-400/25 blur-sm"
          aria-hidden="true"
        />

        {/* Decorative only: the MEDORA wordmark beside it carries the accessible name. */}
        <svg
          width={dimensions.icon}
          height={dimensions.icon}
          viewBox="0 0 100 100"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
          focusable="false"
          className="relative drop-shadow-sm motion-safe:transition-transform motion-safe:duration-300 motion-safe:hover:scale-105"
        >
          <defs>
            {/* Medora Aurora Waves Gradient */}
            <linearGradient id="medoraAuroraWave" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#0072CE" />
              <stop offset="45%" stopColor="#00D2C4" />
              <stop offset="100%" stopColor="#10B981" />
            </linearGradient>

            {/* Cross Body Gradient */}
            <linearGradient id="medoraCrossGrad" x1="0%" y1="100%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#003B73" />
              <stop offset="60%" stopColor="#0072CE" />
              <stop offset="100%" stopColor="#00D2C4" />
            </linearGradient>

            {/* Spark of Clarity Glow */}
            <radialGradient id="claritySpark" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#FFFFFF" stopOpacity="1" />
              <stop offset="50%" stopColor="#E0F7FA" stopOpacity="0.8" />
              <stop offset="100%" stopColor="#00D2C4" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* Rounded Squircle Container */}
          <rect
            x="2"
            y="2"
            width="96"
            height="96"
            rx="26"
            fill="url(#medoraCrossGrad)"
            stroke="rgba(255,255,255,0.25)"
            strokeWidth="2.5"
          />

          {/* Flowing Aurora Light Ribbon / Wave */}
          <path
            d="M 16 68 C 30 78, 48 42, 64 52 C 76 60, 84 56, 88 44 C 84 34, 72 32, 60 40 C 44 50, 32 30, 18 42 Z"
            fill="url(#medoraAuroraWave)"
            opacity="0.85"
          />

          {/* Medical Cross Geometry fused with Light Rays */}
          {/* Vertical Arm */}
          <rect x="42" y="18" width="16" height="64" rx="8" fill="#FFFFFF" fillOpacity="0.95" />
          {/* Horizontal Arm */}
          <rect x="18" y="42" width="64" height="16" rx="8" fill="#FFFFFF" fillOpacity="0.95" />

          {/* Inner Aurora Core Glow */}
          <circle cx="50" cy="50" r="14" fill="url(#medoraAuroraWave)" opacity="0.9" />

          {/* Center Star of Clarity - static: the glow gradient already supplies the highlight,
              and a permanently pulsing brand mark is persistent motion on every screen. */}
          <path
            d="M 50 38 Q 50 50 62 50 Q 50 50 50 62 Q 50 50 38 50 Q 50 50 50 38 Z"
            fill="#FFFFFF"
          />
          <circle cx="50" cy="50" r="3.5" fill="#FFFFFF" />
        </svg>
      </div>

      {/* Typography Section */}
      {variant === 'full' && (
        <div className="flex flex-col justify-center">
          <div className="flex items-center space-x-2">
            <span
              className={`font-black tracking-tight text-slate-900 ${dimensions.text} font-sans`}
              style={{ letterSpacing: '-0.025em' }}
            >
              MED<span className="bg-gradient-to-r from-cyan-600 via-teal-600 to-emerald-600 bg-clip-text text-transparent">ORA</span>
            </span>
            <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-cyan-50 text-cyan-800 border border-cyan-200">
              AI Intelligence
            </span>
          </div>

          {showTagline ? (
            <p className={`text-slate-500 font-medium ${dimensions.tagline} leading-tight pt-0.5 tracking-tight`}>
              Bringing clarity to every medical decision
            </p>
          ) : (
            <p className="text-[10px] text-slate-500 font-medium leading-tight">
              Medical + Aurora • Offline Clinical AI
            </p>
          )}
        </div>
      )}
    </div>
  );
};
