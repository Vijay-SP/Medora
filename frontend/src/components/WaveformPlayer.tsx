import React, { useEffect, useRef, useState, useImperativeHandle, forwardRef } from 'react';
import WaveSurfer from 'wavesurfer.js';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  RotateCcw,
  RotateCw,
  ZoomIn,
  ZoomOut,
  SlidersHorizontal,
  Loader2,
  AlertCircle,
  Scissors,
} from 'lucide-react';

export interface WaveformPlayerRef {
  seekToSeconds: (seconds: number) => void;
  playRange: (startSec: number, endSec: number) => void;
  togglePlay: () => void;
  getCurrentTime: () => number;
}

interface WaveformPlayerProps {
  audioUrl: string;
  onTimeUpdate?: (currentTime: number) => void;
}

export const WaveformPlayer = forwardRef<WaveformPlayerRef, WaveformPlayerProps>(
  ({ audioUrl, onTimeUpdate }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const wavesurfer = useRef<WaveSurfer | null>(null);
    const stopAtRef = useRef<number | null>(null);

    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [playbackRate, setPlaybackRate] = useState(1.0);
    const [volume, setVolume] = useState(1.0);
    const [isMuted, setIsMuted] = useState(false);
    const [prevVolume, setPrevVolume] = useState(1.0);
    const [zoomLevel, setZoomLevel] = useState(0); // minPxPerSec zoom
    const [isReady, setIsReady] = useState(false);
    const [showAdvancedControls, setShowAdvancedControls] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [reloadKey, setReloadKey] = useState(0);
    // Bounded evidence playback, so the user understands why audio stopped early
    const [excerpt, setExcerpt] = useState<{ end: number; done: boolean } | null>(null);

    useEffect(() => {
      if (!containerRef.current) return;

      setIsReady(false);
      setLoadError(null);
      setCurrentTime(0);
      setDuration(0);

      const ws = WaveSurfer.create({
        container: containerRef.current,
        waveColor: '#93c5fd', // Light medical blue
        progressColor: '#005596', // Medpark primary blue
        cursorColor: '#ef4444', // Red cursor
        cursorWidth: 2,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        height: 64,
        url: audioUrl,
        minPxPerSec: 0,
      });

      ws.on('ready', () => {
        const d = ws.getDuration();
        setDuration(d);
        setIsReady(true);
      });

      ws.on('error', () => {
        setIsReady(false);
        setLoadError('Could not load the recording.');
      });

      ws.on('audioprocess', () => {
        const cur = ws.getCurrentTime();
        setCurrentTime(cur);
        if (onTimeUpdate) onTimeUpdate(cur);

        if (stopAtRef.current !== null && cur >= stopAtRef.current) {
          const end = stopAtRef.current;
          ws.pause();
          stopAtRef.current = null;
          setExcerpt({ end, done: true });
        }
      });

      ws.on('seeking', () => {
        const cur = ws.getCurrentTime();
        setCurrentTime(cur);
        if (onTimeUpdate) onTimeUpdate(cur);
      });

      ws.on('play', () => {
        setIsPlaying(true);
        // A finished excerpt notice is stale as soon as playback resumes
        setExcerpt((prev) => (prev && prev.done ? null : prev));
      });
      ws.on('pause', () => setIsPlaying(false));
      ws.on('finish', () => {
        setIsPlaying(false);
        stopAtRef.current = null;
        setExcerpt(null);
      });

      wavesurfer.current = ws;

      return () => {
        ws.destroy();
      };
    }, [audioUrl, reloadKey]);

    useImperativeHandle(ref, () => ({
      seekToSeconds: (seconds: number) => {
        stopAtRef.current = null;
        setExcerpt(null);
        if (wavesurfer.current && duration > 0) {
          const progress = Math.min(1.0, Math.max(0.0, seconds / duration));
          wavesurfer.current.seekTo(progress);
          wavesurfer.current.play();
        }
      },
      playRange: (startSec: number, endSec: number) => {
        if (wavesurfer.current && duration > 0) {
          stopAtRef.current = endSec;
          setExcerpt({ end: endSec, done: false });
          const progress = Math.min(1.0, Math.max(0.0, startSec / duration));
          wavesurfer.current.seekTo(progress);
          wavesurfer.current.play();
        }
      },
      togglePlay: () => {
        if (wavesurfer.current) {
          wavesurfer.current.playPause();
        }
      },
      getCurrentTime: () => {
        return wavesurfer.current ? wavesurfer.current.getCurrentTime() : 0;
      },
    }));

    const togglePlay = () => {
      if (wavesurfer.current) {
        wavesurfer.current.playPause();
      }
    };

    const handleSkip = (seconds: number) => {
      if (wavesurfer.current && duration > 0) {
        const newTime = Math.min(duration, Math.max(0, currentTime + seconds));
        const progress = newTime / duration;
        wavesurfer.current.seekTo(progress);
      }
    };

    const handleRateChange = () => {
      const rates = [0.75, 1.0, 1.25, 1.5, 2.0];
      const nextIdx = (rates.indexOf(playbackRate) + 1) % rates.length;
      const nextRate = rates[nextIdx];
      setPlaybackRate(nextRate);
      if (wavesurfer.current) {
        wavesurfer.current.setPlaybackRate(nextRate);
      }
    };

    const handleVolumeChange = (newVol: number) => {
      setVolume(newVol);
      if (newVol === 0) {
        setIsMuted(true);
      } else {
        setIsMuted(false);
      }
      if (wavesurfer.current) {
        wavesurfer.current.setVolume(newVol);
      }
    };

    const toggleMute = () => {
      if (isMuted) {
        setIsMuted(false);
        const restoreVol = prevVolume > 0 ? prevVolume : 1.0;
        setVolume(restoreVol);
        if (wavesurfer.current) wavesurfer.current.setVolume(restoreVol);
      } else {
        setPrevVolume(volume);
        setIsMuted(true);
        setVolume(0);
        if (wavesurfer.current) wavesurfer.current.setVolume(0);
      }
    };

    const handleZoomChange = (newZoom: number) => {
      setZoomLevel(newZoom);
      if (wavesurfer.current) {
        wavesurfer.current.zoom(newZoom);
      }
    };

    const formatTime = (secs: number) => {
      const m = Math.floor(secs / 60);
      const s = Math.floor(secs % 60);
      return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    };

    return (
      <div
        role="region"
        aria-label="Meeting audio player"
        className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm space-y-3"
      >
        {/* Waveform Canvas */}
        <div className="relative bg-slate-50 rounded-xl p-2 border border-slate-100 overflow-hidden">
          <div ref={containerRef} aria-hidden="true" className="w-full rounded-lg overflow-x-auto" />
          {loadError ? (
            <div className="absolute inset-0 bg-rose-50/95 flex flex-col items-center justify-center text-center px-4 space-y-2">
              <p role="status" className="inline-flex items-center space-x-1.5 text-xs text-rose-800 font-medium">
                <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
                <span>{loadError} Audio playback and evidence links are unavailable.</span>
              </p>
              <button
                onClick={() => setReloadKey((k) => k + 1)}
                className="inline-flex items-center space-x-1.5 px-2.5 py-1 bg-white text-rose-700 border border-rose-200 rounded-lg text-xs font-semibold hover:bg-rose-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/40"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Reload audio</span>
              </button>
            </div>
          ) : (
            !isReady && (
              <div className="absolute inset-0 bg-slate-50/90 flex items-center justify-center">
                <p role="status" className="inline-flex items-center space-x-2 text-xs text-slate-600 font-medium">
                  <Loader2 className="w-4 h-4 text-medpark-500 animate-spin motion-reduce:animate-none" />
                  <span>Loading the recording</span>
                </p>
              </div>
            )
          )}
        </div>

        {/* Bounded evidence playback notice */}
        {excerpt && !loadError && (
          <p
            role="status"
            className="inline-flex items-center space-x-1.5 text-[11px] font-medium text-blue-800 bg-blue-50 border border-blue-200 px-2 py-1 rounded-md"
          >
            <Scissors className="w-3.5 h-3.5 text-blue-600 shrink-0" />
            <span>
              {excerpt.done
                ? `Evidence excerpt ended at ${formatTime(excerpt.end)}. Press play to continue past it.`
                : `Playing evidence excerpt — stops at ${formatTime(excerpt.end)}.`}
            </span>
          </p>
        )}

        {/* Audio Controls Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-1">
          {/* Main Transport Controls */}
          <div className="flex items-center space-x-2">
            <button
              onClick={togglePlay}
              disabled={!isReady || !!loadError}
              className="w-10 h-10 rounded-full bg-medpark-500 text-white flex items-center justify-center hover:bg-medpark-600 transition-all shadow-sm disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/50 focus-visible:ring-offset-2"
              title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
              aria-label={isPlaying ? 'Pause recording' : 'Play recording'}
            >
              {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 ml-0.5" />}
            </button>

            {/* Skip -5s */}
            <button
              onClick={() => handleSkip(-5)}
              disabled={!isReady || !!loadError}
              className="p-2 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Skip backward 5 seconds"
              aria-label="Skip backward 5 seconds"
            >
              <RotateCcw className="w-4 h-4" />
            </button>

            {/* Skip +5s */}
            <button
              onClick={() => handleSkip(5)}
              disabled={!isReady || !!loadError}
              className="p-2 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Skip forward 5 seconds"
              aria-label="Skip forward 5 seconds"
            >
              <RotateCw className="w-4 h-4" />
            </button>

            {/* Time display */}
            <div className="text-xs font-mono font-semibold tabular-nums text-slate-800 bg-slate-100 px-2.5 py-1.5 rounded-lg border border-slate-200">
              <span className="sr-only">Position </span>
              <span>{formatTime(currentTime)}</span>
              <span className="text-slate-400 mx-1" aria-hidden="true">/</span>
              <span className="sr-only">of </span>
              <span className="text-slate-500">{formatTime(duration)}</span>
            </div>
          </div>

          {/* Secondary Controls: Speed, Volume, Zoom & Advanced */}
          <div
            tabIndex={0}
            role="group"
            aria-label="Playback settings"
            className="flex items-center space-x-2.5 overflow-x-auto pb-1 sm:pb-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 rounded-lg"
          >
            {/* Speed Toggle */}
            <button
              onClick={handleRateChange}
              className="px-2.5 py-1.5 text-xs font-bold tabular-nums bg-slate-100 text-slate-700 hover:bg-slate-200 rounded-lg border border-slate-200 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Playback Speed"
              aria-label={`Playback speed ${playbackRate}x`}
            >
              {playbackRate}x
            </button>

            {/* Volume Control */}
            <div className="flex items-center space-x-1.5 bg-slate-50 px-2 py-1 rounded-lg border border-slate-200">
              <button
                onClick={toggleMute}
                className="text-slate-500 hover:text-slate-800 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
                title={isMuted ? 'Unmute' : 'Mute'}
                aria-label="Mute audio"
                aria-pressed={isMuted || volume === 0}
              >
                {isMuted || volume === 0 ? (
                  <VolumeX className="w-4 h-4 text-rose-500" />
                ) : (
                  <Volume2 className="w-4 h-4" />
                )}
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={isMuted ? 0 : volume}
                onChange={(e) => handleVolumeChange(parseFloat(e.target.value))}
                className="w-16 h-1 bg-slate-300 rounded-lg appearance-none cursor-pointer accent-medpark-500"
                title="Volume slider"
                aria-label="Volume"
                aria-valuetext={`${Math.round((isMuted ? 0 : volume) * 100)} percent`}
              />
            </div>

            {/* Advanced Toggle (Zoom controls) */}
            <button
              onClick={() => setShowAdvancedControls(!showAdvancedControls)}
              className={`p-1.5 rounded-lg border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40 ${
                showAdvancedControls
                  ? 'bg-medpark-50 border-medpark-500/30 text-medpark-700'
                  : 'bg-slate-50 border-slate-200 text-slate-500 hover:text-slate-800'
              }`}
              title="Waveform Zoom Controls"
              aria-label="Waveform zoom controls"
              aria-expanded={showAdvancedControls}
              aria-controls="waveform-zoom-panel"
            >
              <SlidersHorizontal className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Waveform Zoom Controls Drawer */}
        {showAdvancedControls && (
          <div
            id="waveform-zoom-panel"
            className="flex items-center space-x-3 pt-2 border-t border-slate-100 text-xs text-slate-600 animate-in fade-in duration-150"
          >
            <span className="font-semibold flex items-center space-x-1">
              <ZoomIn className="w-3.5 h-3.5 text-medpark-600" />
              <span>Waveform Zoom:</span>
            </span>
            <button
              onClick={() => handleZoomChange(Math.max(0, zoomLevel - 20))}
              className="p-1 text-slate-500 hover:text-slate-800 bg-slate-100 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Zoom out waveform"
              aria-label="Zoom out waveform"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <input
              type="range"
              min="0"
              max="200"
              step="10"
              value={zoomLevel}
              onChange={(e) => handleZoomChange(parseInt(e.target.value, 10))}
              className="w-32 h-1 bg-slate-300 rounded-lg appearance-none cursor-pointer accent-medpark-500"
              aria-label="Waveform zoom"
              aria-valuetext={zoomLevel === 0 ? 'Fit to width' : `${zoomLevel} pixels per second`}
            />
            <button
              onClick={() => handleZoomChange(Math.min(200, zoomLevel + 20))}
              className="p-1 text-slate-500 hover:text-slate-800 bg-slate-100 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-medpark-500/40"
              title="Zoom in waveform"
              aria-label="Zoom in waveform"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <span className="text-[11px] font-mono tabular-nums text-slate-500">
              {zoomLevel === 0 ? 'Fit to width' : `${zoomLevel}px/sec`}
            </span>
          </div>
        )}
      </div>
    );
  }
);
