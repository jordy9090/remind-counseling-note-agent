"""Run one isolated local pipeline and save inspectable artifacts for synthetic data."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from threading import Event, Thread
import time

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.services.local_audio_pipeline import LocalAudioConfig, LocalAudioPipeline
from app.services.upload_validation import ValidatedUpload
from benchmarks.stt_evaluate import evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", choices=["faster-whisper", "sensevoice", "whisperx"], required=True)
    parser.add_argument("--beam", type=int, default=1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model")
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--context", type=float, default=2, help="Seconds of context outside each 120-second core")
    parser.add_argument("--whisper-vad-mode", choices=["concatenate", "segments", "clips"], default="concatenate")
    parser.add_argument("--hallucination-silence", type=float)
    parser.add_argument("--diarization", choices=["campplus", "disabled"], default="campplus")
    parser.add_argument("--no-itn", action="store_true")
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    if reference.get("synthetic") is not True:
        raise ValueError("Benchmark accepts explicitly synthetic fixtures only")
    if hashlib.sha256(args.audio.read_bytes()).hexdigest() != reference["audio_sha256"]:
        raise ValueError("Audio does not match reference hash")
    args.output.mkdir(parents=True, exist_ok=True)
    config = LocalAudioConfig(engine=args.engine if args.engine != "whisperx" else "faster-whisper",
        model=args.model or ("FunAudioLLM/SenseVoiceSmall" if args.engine == "sensevoice" else "large-v3"), device=args.device,
        compute_type="int8" if args.device == "cpu" else "float16", beam_size=args.beam, batch_size=args.batch,
        diarization=args.diarization, use_itn=not args.no_itn, max_duration_seconds=3600, context_seconds=args.context,
        whisper_vad_mode=args.whisper_vad_mode, hallucination_silence_seconds=args.hallucination_silence)
    metadata = {"config": asdict(config), "engine": args.engine, "platform": platform.platform(),
                "audio_sha256": reference["audio_sha256"], "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "packages": {}}
    metadata["precision"] = {"asr": "float32 (FunASR default)" if args.engine == "sensevoice" else config.compute_type,
                             "speaker_embeddings": "float32 (FunASR default)",
                             "alignment": "float32" if args.engine == "whisperx" else "not used"}
    for package in ["faster-whisper", "ctranslate2", "funasr", "torch", "torchaudio", "whisperx", "transformers", "numpy"]:
        try:
            metadata["packages"][package] = version(package)
        except PackageNotFoundError:
            pass
    stop = Event()
    memory = {"peak_rss_bytes": 0, "peak_process_gpu_mib": None, "gpu_measurement": "not available (CPU or nvidia-smi unavailable)"}

    def sample():
        import psutil
        process = psutil.Process()
        while not stop.is_set():
            memory["peak_rss_bytes"] = max(memory["peak_rss_bytes"], process.memory_info().rss)
            if args.device != "cpu":
                try:
                    report = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"], text=True, timeout=3)
                    used = [int(line.split(",")[1]) for line in report.splitlines() if line.split(",")[0].strip() == str(os.getpid())]
                    if used:
                        memory["peak_process_gpu_mib"] = max(memory["peak_process_gpu_mib"] or 0, sum(used))
                        memory["gpu_measurement"] = "nvidia-smi per-process sample every 0.5s; includes CTranslate2"
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            stop.wait(0.5)
    worker = Thread(target=sample, daemon=True)
    worker.start()
    start = time.perf_counter()
    try:
        upload = ValidatedUpload(args.audio.name, "audio/wav", ".wav", args.audio.stat().st_size, args.audio.resolve())
        if args.engine == "whisperx":
            from app.services.audio_transcription import WhisperXTranscriptionService, current_whisperx_config
            os.environ.update(WHISPERX_DEVICE=args.device, WHISPERX_COMPUTE_TYPE=config.compute_type,
                              WHISPERX_BATCH_SIZE=str(args.batch), ENABLE_AUDIO_DIARIZATION="1")
            baseline_config = current_whisperx_config()
            metadata["legacy_config"] = asdict(baseline_config)
            service = WhisperXTranscriptionService(baseline_config)
        else:
            service = LocalAudioPipeline(config, progress=lambda event: print(json.dumps(event), flush=True))
        output = service.transcribe(upload, language="ko", expected_speakers=2).model_dump()
        output.setdefault("stage_metrics", {})["benchmark_wall_seconds"] = time.perf_counter() - start
        output["stage_metrics"]["benchmark_rtf"] = (time.perf_counter() - start) / reference["duration_seconds"]
        (args.output / "transcription.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        score = evaluate(reference, output)
        (args.output / "metrics.json").write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": output["status"], "cer": score["korean_cer"], "output": str(args.output)}), flush=True)
    except Exception as error:
        metadata["failure_type"] = type(error).__name__
        # No raw audio, transcript or exception details in service logs.
        (args.output / "failure.json").write_text(json.dumps({"type": type(error).__name__, "message": str(error)[:500]}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        stop.set()
        worker.join(timeout=5)
        metadata.update(memory=memory, wall_seconds=time.perf_counter() - start)
        (args.output / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
