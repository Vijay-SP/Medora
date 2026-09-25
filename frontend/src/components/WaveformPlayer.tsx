import React, { useEffect, useRef, useState, useImperativeHandle, forwardRef } from 'react';
import WaveSurfer from 'wavesurfer.js';
import { Play, Pause, Volume2, RotateCcw, FastForward } from 'lucide-react';

export interface WaveformPlayerRef {
  seekToSeconds: (seconds: number) => void;
  playRange: (startSec: number, endSec: number) => void;
}

interface WaveformPlayerProps {
  audioUrl: string;
}

export const WaveformPlayer = forwardRef<WaveformPlayerRef, WaveformPlayerProps>(({ audioUrl }, ref) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const wavesurfer = useRef<WaveSurfer | null>(null);
  const stopAtRef = useRef<number | null>(null);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;

    // Initialize WaveSurfer
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
    });

    ws.on('ready', () => {
      setDuration(ws.getDuration());
      setIsReady(true);
    });

    ws.on('audioprocess', () => {
      const cur = ws.getCurrentTime();
      setCurrentTime(cur);
      if (stopAtRef.current !== null && cur >= stopAtRef.current) {
        ws.pause();
        stopAtRef.current = null;
      }
    });

    ws.on('seeking', () => {
      setCurrentTime(ws.getCurrentTime());
    });

    ws.on('play', () => setIsPlaying(true));
    ws.on('pause', () => setIsPlaying(false));
    ws.on('finish', () => {
      setIsPlaying(false);
      stopAtRef.current = null;
    });

    wavesurfer.current = ws;

    return () => {
      ws.destroy();
    };
  }, [audioUrl]);

  useImperativeHandle(ref, () => ({
    seekToSeconds: (seconds: number) => {
      stopAtRef.current = null;
      if (wavesurfer.current && duration > 0) {
        const progress = Math.min(1.0, Math.max(0.0, seconds / duration));
        wavesurfer.current.seekTo(progress);
        wavesurfer.current.play();
      }
    },
    playRange: (startSec: number, endSec: number) => {
      if (wavesurfer.current && duration > 0) {
        stopAtRef.current = endSec;
        const progress = Math.min(1.0, Math.max(0.0, startSec / duration));
        wavesurfer.current.seekTo(progress);
        wavesurfer.current.play();
      }
    },
  }));

  const togglePlay = () => {
    if (wavesurfer.current) {
      wavesurfer.current.playPause();
    }
  };

  const handleRateChange = () => {
    const rates = [1.0, 1.25, 1.5, 2.0];
    const nextIdx = (rates.indexOf(playbackRate) + 1) % rates.length;
    const nextRate = rates[nextIdx];
    setPlaybackRate(nextRate);
    if (wavesurfer.current) {
      wavesurfer.current.setPlaybackRate(nextRate);
    }
  };

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm space-y-3">
      {/* Waveform Canvas */}
      <div className="relative">
        <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />
        {!isReady && (
          <div className="absolute inset-0 bg-slate-50/80 flex items-center justify-center text-xs text-slate-500 font-medium">
            Loading audio visualization...
          </div>
        )}
      </div>

      {/* Audio Controls Bar */}
      <div className="flex items-center justify-between pt-2 border-t border-slate-100">
        <div className="flex items-center space-x-3">
          <button
            onClick={togglePlay}
            disabled={!isReady}
            className="w-10 h-10 rounded-full bg-medpark-500 text-white flex items-center justify-center hover:bg-medpark-600 transition-colors shadow-sm disabled:opacity-50"
            title={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 ml-0.5" />}
          </button>

          <div className="text-sm font-mono font-medium text-slate-700">
            <span>{formatTime(currentTime)}</span>
            <span className="text-slate-400 mx-1">/</span>
            <span className="text-slate-500">{formatTime(duration)}</span>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={() => {
              if (wavesurfer.current) {
                wavesurfer.current.seekTo(0);
              }
            }}
            className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors"
            title="Restart from beginning"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          <button
            onClick={handleRateChange}
            className="px-2.5 py-1 text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 rounded-md transition-colors"
            title="Change playback speed"
          >
            {playbackRate}x
          </button>
        </div>
      </div>
    </div>
  );
});
