import React, { useState, useRef, useEffect } from 'react';
import { Mic, Square, AlertCircle } from 'lucide-react';

interface AudioRecorderProps {
  onAudioReady: (file: File) => void;
  disabled?: boolean;
}

const getSupportedAudioMimeType = (): { mimeType: string; extension: string } => {
  const candidates = [
    { mimeType: 'audio/webm;codecs=opus', extension: 'webm' },
    { mimeType: 'audio/webm', extension: 'webm' },
    { mimeType: 'audio/mp4', extension: 'mp4' },
    { mimeType: 'audio/ogg;codecs=opus', extension: 'ogg' },
    { mimeType: 'audio/wav', extension: 'wav' },
  ];
  for (const c of candidates) {
    if (typeof MediaRecorder !== 'undefined' && typeof MediaRecorder.isTypeSupported === 'function') {
      if (MediaRecorder.isTypeSupported(c.mimeType)) {
        return c;
      }
    }
  }
  return { mimeType: '', extension: 'wav' };
};

export const AudioRecorder: React.FC<AudioRecorderProps> = ({ onAudioReady, disabled }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const activeFormatRef = useRef<{ mimeType: string; extension: string }>({ mimeType: 'audio/webm', extension: 'webm' });

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        try {
          mediaRecorderRef.current.stop();
        } catch (_) {}
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
    };
  }, []);

  const startRecording = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const format = getSupportedAudioMimeType();
      activeFormatRef.current = format;
      const options = format.mimeType ? { mimeType: format.mimeType } : undefined;
      const mediaRecorder = new MediaRecorder(stream, options);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        const mime = activeFormatRef.current.mimeType || 'audio/wav';
        const ext = activeFormatRef.current.extension || 'wav';
        const audioBlob = new Blob(audioChunksRef.current, { type: mime });
        const audioFile = new File([audioBlob], `medpark_record_${Date.now()}.${ext}`, {
          type: mime,
        });
        onAudioReady(audioFile);

        // Stop all tracks to release microphone hardware
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((track) => track.stop());
          streamRef.current = null;
        }
      };

      mediaRecorder.start(500); // 500ms chunking
      setIsRecording(true);
      setSeconds(0);

      timerRef.current = window.setInterval(() => {
        setSeconds((prev) => prev + 1);
      }, 1000);
    } catch (err: any) {
      console.error('Microphone access denied:', err);
      // Name the failure and the way out of it: a bare "denied" leaves the user stuck.
      if (err?.name === 'NotFoundError' || err?.name === 'DevicesNotFoundError') {
        setError('No microphone was found. Connect a microphone, then try again — or upload an audio file instead.');
      } else if (err?.name === 'NotAllowedError' || err?.name === 'SecurityError') {
        setError('Microphone access was blocked. Allow the microphone for this site in your browser address bar, then try again.');
      } else {
        setError('Recording could not start on this device. Upload an audio file instead.');
      }
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
  };

  const formatTimer = (totalSecs: number) => {
    const m = Math.floor(totalSecs / 60);
    const s = totalSecs % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center space-x-3">
        {!isRecording ? (
          <button
            type="button"
            onClick={startRecording}
            disabled={disabled}
            className="inline-flex items-center space-x-2 px-4 py-2 rounded-lg bg-rose-600 text-white font-medium text-sm hover:bg-rose-700 transition-colors shadow-sm disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:ring-offset-2"
          >
            <Mic className="w-4 h-4" aria-hidden="true" />
            <span>Start Recording</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={stopRecording}
            className="inline-flex items-center space-x-2 px-4 py-2 rounded-lg bg-slate-900 text-white font-medium text-sm hover:bg-black transition-colors shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2"
          >
            <Square className="w-4 h-4 text-rose-500 fill-rose-500" aria-hidden="true" />
            <span>
              Stop <span className="font-mono tabular-nums">({formatTimer(seconds)})</span>
            </span>
          </button>
        )}

        {isRecording && (
          // State is carried by the REC label and the timer, not by the animation alone.
          <span className="flex items-center space-x-1.5 text-xs text-rose-700 font-semibold">
            <span className="w-2 h-2 rounded-full bg-rose-600 motion-safe:animate-ping" aria-hidden="true" />
            <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-rose-50 border border-rose-200">
              Rec
            </span>
            <span role="timer" aria-live="off" className="font-mono tabular-nums">
              {formatTimer(seconds)}
            </span>
            <span className="sr-only">Recording in progress</span>
          </span>
        )}
      </div>

      {error && (
        <div role="alert" className="flex items-start space-x-1.5 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-px text-rose-600" aria-hidden="true" />
          <span className="leading-relaxed">{error}</span>
        </div>
      )}
    </div>
  );
};
