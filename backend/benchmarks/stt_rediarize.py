"""Re-evaluate only diarization/merge against a frozen synthetic ASR artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.schemas.audio import AudioInterval, AudioSegment
from app.services.local_audio_pipeline import LocalAudioConfig, LocalAudioPipeline, merge_speakers
from benchmarks.stt_evaluate import evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    source = json.loads((args.source / "transcription.json").read_text(encoding="utf-8"))
    metadata = json.loads((args.source / "run.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(args.audio.read_bytes()).hexdigest()
    if not reference.get("synthetic") or digest != reference["audio_sha256"] or digest != metadata["audio_sha256"]:
        raise ValueError("Only matching frozen synthetic audio and ASR artifacts are accepted")
    config = LocalAudioConfig(**metadata["config"])
    pipeline = LocalAudioPipeline(config, progress=lambda event: print(json.dumps(event), flush=True))
    raw = [AudioSegment(**s) for s in source["raw_segments"]]
    start = time.perf_counter()
    spans = pipeline.diarize(args.audio, [AudioInterval(**s) for s in source["vad_segments"]], 2)
    source["diarization_segments"] = [s.model_dump() for s in spans]
    source["segments"] = [s.model_dump() for s in merge_speakers(raw, spans)]
    source["transcript_text"] = "\n".join(s["text"] for s in source["segments"])
    source["diarization_status"] = "completed"
    source["stage_metrics"]["diarization_seconds"] = time.perf_counter() - start
    # These are composite stage sums, not a fresh complete wall-time measurement.
    source["stage_metrics"]["total_seconds"] = sum(source["stage_metrics"][key] for key in ("decode_seconds", "asr_seconds", "diarization_seconds"))
    source["stage_metrics"]["real_time_factor"] = source["stage_metrics"]["total_seconds"] / reference["duration_seconds"]
    source["stage_metrics"].pop("benchmark_wall_seconds", None)
    source["stage_metrics"].pop("benchmark_rtf", None)
    metadata["asr_reused_from"] = str(args.source)
    metadata["asr_artifact_sha256"] = hashlib.sha256((args.source / "transcription.json").read_bytes()).hexdigest()
    metadata["timing_note"] = "ASR unchanged; only diarization+merge rerun. Total is composite stage sum. Memory belongs to original full run."
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, data in (("transcription.json", source), ("metrics.json", evaluate(reference, source)), ("run.json", metadata)):
        (args.output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "diarization_seconds": source["stage_metrics"]["diarization_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
