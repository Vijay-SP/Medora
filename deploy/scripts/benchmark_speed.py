"""
Medpark Meeting Intelligence System - Speed & Performance Benchmark
Measures end-to-end processing latency against the challenge target (<15 min for 60 min audio).
"""

import sys
import time
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

import asyncio
from datetime import datetime
from app.models.meeting import Meeting, MeetingType, WorkflowMode, Attendee
from app.storage.repository import repository
from app.services.pipeline_orchestrator import pipeline_orchestrator


async def benchmark_audio(audio_path: Path):
    if not audio_path.exists():
        print(f"Error: Target audio file not found: {audio_path}")
        sys.exit(1)

    print("==================================================================")
    print("MEDPARK MEETING INTELLIGENCE - SPEED & LATENCY BENCHMARK")
    print(f"Audio File: {audio_path.name} ({audio_path.stat().st_size / (1024*1024):.2f} MB)")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("==================================================================")

    # 1. Create Benchmark Meeting Record
    # SUPERVISED, with attendees on the unroutable .invalid domain: the benchmark measures
    # processing latency only and must never dispatch mail to real hospital recipients.
    meeting = Meeting(
        title=f"Benchmark Test - {audio_path.stem}",
        meeting_type=MeetingType.MEDICAL,
        workflow_mode=WorkflowMode.SUPERVISED,
        attendees=[
            Attendee(name="Benchmark Participant 1", role="Chirurg Șef", email="participant1@benchmark.invalid"),
            Attendee(name="Benchmark Participant 2", role="Șef ATI", email="participant2@benchmark.invalid")
        ]
    )
    meeting.original_audio_path = str(audio_path)
    repository.save_meeting(meeting)

    t0 = time.time()
    completed = await pipeline_orchestrator.run_pipeline(meeting.id)
    total_time = time.time() - t0

    audio_len = completed.audio_duration_seconds
    rtf = total_time / max(1.0, audio_len)  # Real-Time Factor
    extrapolated_60min = rtf * 3600.0  # Projected processing time for 60 min recording (seconds)
    extrapolated_60min_min = extrapolated_60min / 60.0

    print("\n------------------------- BENCHMARK RESULTS -------------------------")
    print(f"Actual Audio Duration:            {audio_len:.2f} seconds ({audio_len/60:.2f} minutes)")
    print(f"End-to-End Processing Time:       {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print(f"Real-Time Factor (RTF):           {rtf:.3f}x")
    print(f"Extrapolated 60-min Audio Time:   {extrapolated_60min_min:.2f} minutes")
    print(f"Challenge Budget Target (<15m):   {'PASS (Under 15 minutes!)' if extrapolated_60min_min <= 15.0 else 'WARN (>15 minutes)'}")
    print("---------------------------------------------------------------------\n")


if __name__ == "__main__":
    test_file = Path("data/fixtures/Medpark_audio.m4a")
    if len(sys.argv) > 1:
        test_file = Path(sys.argv[1])
    asyncio.run(benchmark_audio(test_file))
