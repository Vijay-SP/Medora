import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Mic,
  Square,
  Pause,
  Play,
  Sparkles,
  AlertCircle,
  Users,
  Plus,
  Trash2,
  Sliders,
  ShieldCheck,
  Radio,
  FileCheck,
  CheckCircle2,
} from 'lucide-react';
import { MeetingCreate, MeetingType, WorkflowMode, Attendee } from '../types';
import { ParticipantSelector } from './ParticipantSelector';

interface LiveMeetingStudioProps {
  onMeetingRecorded: (payload: MeetingCreate, audioFile: File) => Promise<void>;
  onCancel?: () => void;
}

export const LiveMeetingStudio: React.FC<LiveMeetingStudioProps> = ({
  onMeetingRecorded,
  onCancel,
}) => {
  // Meeting metadata
  const [title, setTitle] = useState(() => {
    const d = new Date();
    return `Medical Board - Case Review (${d.toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
    })})`;
  });
  const [meetingType, setMeetingType] = useState<MeetingType>('medical');
  const [workflowMode, setWorkflowMode] = useState<WorkflowMode>('supervised');
  const [agenda, setAgenda] = useState('');
  const [attendees, setAttendees] = useState<Attendee[]>([]);

  // Recording & Hardware state
  const [isRecording, setIsRecording] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [audioDevices, setAudioDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('');
  const [volumeLevel, setVolumeLevel] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isProcessingFinal, setIsProcessingFinal] = useState(false);

  // Audio nodes and refs
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerIntervalRef = useRef<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameCountRef = useRef<number>(0);

  // Discover connected microphones (e.g. conference room omni mic vs laptop mic)
  useEffect(() => {
    const enumerate = async () => {
      try {
        if (!navigator.mediaDevices?.enumerateDevices) return;
        const devices = await navigator.mediaDevices.enumerateDevices();
        const inputs = devices.filter((d) => d.kind === 'audioinput');
        setAudioDevices(inputs);
        if (inputs.length > 0 && !selectedDeviceId) {
          setSelectedDeviceId(inputs[0].deviceId);
        }
      } catch (err) {
        console.warn('Could not enumerate audio devices:', err);
      }
    };
    enumerate();
  }, [selectedDeviceId]);

  // Teardown audio on unmount
  useEffect(() => {
    return () => {
      cleanupAudio();
    };
  }, []);

  const cleanupAudio = () => {
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
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
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
  };

  // Draw resting idle state on canvas
  const drawIdleWaveform = useCallback(() => {
    if (!canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    const barCount = 48;
    const barWidth = (width / barCount) - 2;

    for (let i = 0; i < barCount; i++) {
      const barHeight = 4;
      const x = i * (barWidth + 2);
      const y = (height - barHeight) / 2;

      ctx.fillStyle = '#1e293b'; // slate-800
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(x, y, barWidth, barHeight, 2) : ctx.rect(x, y, barWidth, barHeight);
      ctx.fill();
    }
  }, []);

  // Initial idle render on mount
  useEffect(() => {
    drawIdleWaveform();
  }, [drawIdleWaveform]);

  // Canvas visualizer loop
  const drawWaveform = useCallback(() => {
    if (!analyserRef.current || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const bufferLength = analyserRef.current.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    analyserRef.current.getByteFrequencyData(dataArray);

    // Compute average amplitude for meter
    let sum = 0;
    for (let i = 0; i < bufferLength; i++) {
      sum += dataArray[i];
    }
    const avg = sum / bufferLength;

    // Throttle React state updates to avoid re-rendering entire tree at 60 FPS
    frameCountRef.current = (frameCountRef.current || 0) + 1;
    if (frameCountRef.current % 6 === 0) {
      setVolumeLevel(Math.min(100, Math.round((avg / 128) * 100)));
    }

    // Render bars on canvas
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    const barCount = 48;
    const barWidth = (width / barCount) - 2;
    const step = Math.max(1, Math.floor(bufferLength / barCount));

    for (let i = 0; i < barCount; i++) {
      const val = dataArray[i * step] || 0;
      const percent = val / 255;
      const barHeight = Math.max(4, percent * height);
      const x = i * (barWidth + 2);
      const y = height - barHeight;

      // Gradient color: blue to teal to emerald green
      const grad = ctx.createLinearGradient(0, height, 0, 0);
      grad.addColorStop(0, '#0284c7');
      grad.addColorStop(0.6, '#0d9488');
      grad.addColorStop(1, '#10b981');

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(x, y, barWidth, barHeight, 3) : ctx.rect(x, y, barWidth, barHeight);
      ctx.fill();
    }

    animationFrameRef.current = requestAnimationFrame(drawWaveform);
  }, []);

  // Reactive visualizer controller: starts on record, pauses on pause, resets to idle on stop
  useEffect(() => {
    if (isRecording && !isPaused) {
      if (audioContextRef.current && audioContextRef.current.state === 'suspended') {
        audioContextRef.current.resume().catch(() => {});
      }
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      animationFrameRef.current = requestAnimationFrame(drawWaveform);
    } else {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      if (!isRecording) {
        setVolumeLevel(0);
        drawIdleWaveform();
      }
    }
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [isRecording, isPaused, drawWaveform, drawIdleWaveform]);

  const startLiveRecording = async () => {
    setErrorMessage(null);
    try {
      const constraints: MediaStreamConstraints = {
        audio: selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : true,
      };

      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;

      // Set up AudioContext for real-time visualization
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      const audioCtx = new AudioCtx();
      if (audioCtx.state === 'suspended') {
        await audioCtx.resume();
      }
      audioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Configure MediaRecorder
      const mimeTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', 'audio/mp4'];
      let selectedMime = '';
      for (const m of mimeTypes) {
        if (MediaRecorder.isTypeSupported(m)) {
          selectedMime = m;
          break;
        }
      }

      const recorder = new MediaRecorder(stream, selectedMime ? { mimeType: selectedMime } : undefined);
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.start(1000); // 1-second chunks
      setIsRecording(true);
      setIsPaused(false);
      setElapsedSeconds(0);

      timerIntervalRef.current = window.setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } catch (err: any) {
      console.error('Failed to start live recording:', err);
      if (err?.name === 'NotAllowedError') {
        setErrorMessage('Microphone access was denied. Please allow microphone permissions in your browser.');
      } else if (err?.name === 'NotFoundError') {
        setErrorMessage('No microphone device was detected. Connect your conference room mic and try again.');
      } else {
        setErrorMessage(`Microphone error: ${err?.message || 'Could not start recording'}`);
      }
    }
  };

  const pauseLiveRecording = () => {
    if (mediaRecorderRef.current && isRecording && !isPaused) {
      mediaRecorderRef.current.pause();
      setIsPaused(true);
      if (audioContextRef.current && audioContextRef.current.state === 'running') {
        audioContextRef.current.suspend().catch(() => {});
      }
      if (timerIntervalRef.current) {
        clearInterval(timerIntervalRef.current);
        timerIntervalRef.current = null;
      }
    }
  };

  const resumeLiveRecording = () => {
    if (mediaRecorderRef.current && isRecording && isPaused) {
      mediaRecorderRef.current.resume();
      if (audioContextRef.current && audioContextRef.current.state === 'suspended') {
        audioContextRef.current.resume().catch(() => {});
      }
      setIsPaused(false);
      timerIntervalRef.current = window.setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    }
  };

  const finishAndProcess = async () => {
    if (!mediaRecorderRef.current || !isRecording) return;
    setIsProcessingFinal(true);

    const recorder = mediaRecorderRef.current;

    // Handle recorder stop asynchronously
    recorder.onstop = async () => {
      const mime = recorder.mimeType || 'audio/webm';
      const ext = mime.includes('ogg') ? 'ogg' : mime.includes('mp4') ? 'mp4' : 'webm';
      const audioBlob = new Blob(audioChunksRef.current, { type: mime });
      const audioFile = new File([audioBlob], `live_meeting_${Date.now()}.${ext}`, {
        type: mime,
      });

      cleanupAudio();
      setIsRecording(false);

      const payload: MeetingCreate = {
        title: title.trim() || 'Live Medical Meeting',
        meeting_type: meetingType,
        workflow_mode: workflowMode,
        scheduled_at: new Date().toISOString(),
        attendees,
        agenda: agenda.trim() || undefined,
        distribution_list: [],
      };

      try {
        await onMeetingRecorded(payload, audioFile);
      } catch (err: any) {
        setErrorMessage(`Failed to process recorded meeting: ${err?.message || 'Server error'}`);
        setIsProcessingFinal(false);
      }
    };

    recorder.stop();
  };

  const formatTimer = (secs: number) => {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (h > 0) {
      return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="w-full space-y-6">
      {/* Top Banner */}
      <div className="bg-gradient-to-r from-slate-900 via-medpark-900 to-slate-900 text-white rounded-3xl border border-white/10 p-6 sm:p-7 shadow-sm relative overflow-hidden flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Subtle ambient decorative glow */}
        <div className="absolute -right-20 -top-20 w-80 h-80 bg-medpark-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 space-y-1.5">
          <div className="inline-flex items-center space-x-2 px-3 py-1 bg-rose-500/20 text-rose-300 border border-rose-400/30 rounded-full text-xs font-bold backdrop-blur-xs">
            <Radio className="w-3.5 h-3.5 animate-pulse text-rose-400" />
            <span>Live In-Person Meeting Room</span>
          </div>
          <h2 className="text-xl sm:text-2xl font-black text-white tracking-tight">Conference Room Audio Ingestion</h2>
          <p className="text-xs sm:text-sm text-slate-300 leading-relaxed max-w-2xl">
            Capture live dialogue directly from your conference mic. Medora processes everything 100% offline.
          </p>
          <p className="text-[11px] text-blue-200/90 flex items-center space-x-1.5 pt-0.5">
            <ShieldCheck className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
            <span>Notă EU AI Act (Art. 50): Înregistrarea va fi procesată prin modele AI locale; documentele generate au caracter asistat și necesită validare umană.</span>
          </p>
        </div>

        <div className="flex items-center space-x-2.5 relative z-10 flex-shrink-0">
          <div className="flex items-center space-x-1.5 px-3.5 py-2 bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 rounded-xl text-xs font-semibold backdrop-blur-xs">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>Air-Gapped Recording</span>
          </div>
          {onCancel && !isRecording && (
            <button
              onClick={onCancel}
              className="px-3.5 py-2 text-xs text-slate-300 hover:text-white bg-white/10 hover:bg-white/20 border border-white/15 rounded-xl transition-all font-medium backdrop-blur-xs"
            >
              Exit Studio
            </button>
          )}
        </div>
      </div>

      {/* Error Alert */}
      {errorMessage && (
        <div role="alert" className="p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-800 text-xs flex items-start space-x-2 shadow-sm">
          <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0 mt-0.5" />
          <span className="leading-relaxed">{errorMessage}</span>
        </div>
      )}

      {/* Main Studio Console */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Live Audio Controls & Visualizer */}
        <div className="lg:col-span-6 xl:col-span-7 bg-white p-6 sm:p-7 rounded-2xl border border-slate-200/90 shadow-sm space-y-6">
          <div>
            {/* Audio Device Selector */}
            <div className="space-y-1.5 mb-6">
              <label htmlFor="mic-device-select" className="text-xs font-semibold text-slate-700 flex items-center space-x-1.5">
                <Sliders className="w-3.5 h-3.5 text-slate-500" />
                <span>Audio Input Source</span>
              </label>
              <select
                id="mic-device-select"
                disabled={isRecording}
                value={selectedDeviceId}
                onChange={(e) => setSelectedDeviceId(e.target.value)}
                className="w-full text-xs font-medium px-3 py-2 bg-slate-50 border border-slate-300 rounded-xl text-slate-800 focus:outline-none focus:ring-2 focus:ring-rose-500/20 disabled:opacity-60"
              >
                {audioDevices.length > 0 ? (
                  audioDevices.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || `Microphone (${d.deviceId.slice(0, 8)})`}
                    </option>
                  ))
                ) : (
                  <option value="">Default System Microphone</option>
                )}
              </select>
            </div>

            {/* Central Recording Display */}
            <div className="bg-slate-900 rounded-2xl p-6 text-center text-white relative overflow-hidden shadow-inner">
              {/* Background ambient glow when active */}
              {isRecording && !isPaused && (
                <div className="absolute inset-0 bg-rose-600/10 pointer-events-none animate-pulse" />
              )}

              {/* Status Header */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center space-x-2">
                  <span
                    className={`w-3 h-3 rounded-full ${
                      isRecording
                        ? isPaused
                          ? 'bg-amber-400'
                          : 'bg-rose-500 animate-ping'
                        : 'bg-slate-600'
                    }`}
                  />
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                    {isRecording ? (isPaused ? 'Recording Paused' : 'Live Capture Active') : 'Standby Mode'}
                  </span>
                </div>

                {isRecording && (
                  <div className="flex items-center space-x-1 text-xs text-slate-400 font-mono">
                    <span>Input Level:</span>
                    <span className="font-bold text-emerald-400">{volumeLevel}%</span>
                  </div>
                )}
              </div>

              {/* Large Digital Timer */}
              <div className="py-4">
                <span className="font-mono text-5xl sm:text-6xl font-black tracking-tight text-white tabular-nums drop-shadow-md">
                  {formatTimer(elapsedSeconds)}
                </span>
                <p className="text-[11px] text-slate-400 font-medium uppercase tracking-wider mt-2">
                  {isRecording ? 'Elapsed Conference Duration' : 'Press Start When Attendees Begin'}
                </p>
              </div>

              {/* Real-Time Waveform Canvas */}
              <div className="h-20 w-full mt-2 bg-slate-950/80 rounded-xl overflow-hidden border border-slate-800 relative flex items-center justify-center">
                <canvas
                  ref={canvasRef}
                  width={640}
                  height={80}
                  className={`w-full h-full transition-opacity duration-300 ${
                    isRecording && !isPaused ? 'opacity-100' : 'opacity-40'
                  }`}
                />
                {!isRecording && (
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none bg-slate-950/40">
                    <span className="text-xs text-slate-400 font-mono tracking-wide flex items-center space-x-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                      <span>Visualizer activates during live recording</span>
                    </span>
                  </div>
                )}
                {isRecording && isPaused && (
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none bg-slate-950/60">
                    <span className="text-xs text-amber-400 font-mono font-bold tracking-wider uppercase flex items-center space-x-2">
                      <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
                      <span>Recording Paused</span>
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Action Control Buttons */}
          <div className="space-y-3">
            {!isRecording ? (
              <button
                type="button"
                onClick={startLiveRecording}
                disabled={isProcessingFinal}
                className="w-full flex items-center justify-center space-x-2 px-6 py-4 rounded-xl bg-gradient-to-r from-rose-600 to-rose-700 hover:from-rose-700 hover:to-rose-800 text-white font-black text-sm shadow-md transition-all active:scale-[0.99] focus:outline-none focus:ring-4 focus:ring-rose-500/20"
              >
                <Mic className="w-5 h-5 animate-pulse" />
                <span>Start Live Conference Recording</span>
              </button>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {/* Pause / Resume Button */}
                {!isPaused ? (
                  <button
                    type="button"
                    onClick={pauseLiveRecording}
                    className="flex items-center justify-center space-x-2 px-4 py-3.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-800 font-bold text-xs border border-slate-300 transition-colors"
                  >
                    <Pause className="w-4 h-4 text-slate-700" />
                    <span>Pause Meeting</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={resumeLiveRecording}
                    className="flex items-center justify-center space-x-2 px-4 py-3.5 rounded-xl bg-blue-50 hover:bg-blue-100 text-blue-700 font-bold text-xs border border-blue-200 transition-colors"
                  >
                    <Play className="w-4 h-4 text-blue-600 fill-blue-600" />
                    <span>Resume Meeting</span>
                  </button>
                )}

                {/* Stop & Process Button */}
                <button
                  type="button"
                  onClick={finishAndProcess}
                  disabled={isProcessingFinal}
                  className="flex items-center justify-center space-x-2 px-4 py-3.5 rounded-xl bg-slate-900 hover:bg-black text-white font-bold text-xs shadow-md transition-colors disabled:opacity-50"
                >
                  <Square className="w-4 h-4 text-rose-500 fill-rose-500" />
                  <span>{isProcessingFinal ? 'Processing...' : 'Stop & Generate MoM'}</span>
                </button>
              </div>
            )}

            <p className="text-[11px] text-center text-slate-400">
              When stopped, Medora automatically transcribes with Whisper, attributes clinical speakers, and extracts evidence-grounded MoM.
            </p>
          </div>
        </div>

        {/* Right Column: Meeting Metadata & Participants */}
        <div className="lg:col-span-6 xl:col-span-5 bg-white p-6 sm:p-7 rounded-2xl border border-slate-200/90 shadow-sm space-y-4">
          <h3 className="font-bold text-slate-900 text-sm border-b border-slate-100 pb-2">
            Session Configuration
          </h3>

          {/* Title */}
          <div className="space-y-1">
            <label htmlFor="live-title" className="text-xs font-semibold text-slate-700">
              Meeting Title
            </label>
            <input
              id="live-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Clinical Board - Emergency Protocol"
              className="w-full text-xs px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
          </div>

          {/* Type & Workflow */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label htmlFor="live-type" className="text-xs font-semibold text-slate-700">
                Board Classification
              </label>
              <select
                id="live-type"
                value={meetingType}
                onChange={(e) => setMeetingType(e.target.value as MeetingType)}
                className="w-full text-xs font-semibold px-2.5 py-2 rounded-xl border border-slate-300 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              >
                <option value="medical">Medical Board</option>
                <option value="executive">Executive Committee</option>
                <option value="administrative">Hospital Admin</option>
              </select>
            </div>

            <div className="space-y-1">
              <label htmlFor="live-mode" className="text-xs font-semibold text-slate-700">
                Governance Mode
              </label>
              <select
                id="live-mode"
                value={workflowMode}
                onChange={(e) => setWorkflowMode(e.target.value as WorkflowMode)}
                className="w-full text-xs font-semibold px-2.5 py-2 rounded-xl border border-slate-300 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
              >
                <option value="supervised">Supervised (Reviewer Sign-Off)</option>
                <option value="auto_pilot">Auto-Pilot (Direct Email)</option>
              </select>
            </div>
          </div>

          {/* Agenda */}
          <div className="space-y-1">
            <label htmlFor="live-agenda" className="text-xs font-semibold text-slate-700">
              Agenda Topics (Optional)
            </label>
            <textarea
              id="live-agenda"
              rows={2}
              value={agenda}
              onChange={(e) => setAgenda(e.target.value)}
              placeholder="Key clinical questions or discussion points..."
              className="w-full text-xs px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-medpark-500/20"
            />
          </div>

          {/* Attendees */}
          <div className="pt-2 border-t border-slate-100">
            <ParticipantSelector
              attendees={attendees}
              onChange={setAttendees}
              disabled={isRecording || isProcessingFinal}
            />
          </div>
        </div>
      </div>
    </div>
  );
};
