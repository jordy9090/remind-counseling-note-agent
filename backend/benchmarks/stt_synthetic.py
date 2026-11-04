"""Generate ONLY the checked-in fictional script; never accepts arbitrary input text.

Edge TTS receives synthetic text only, not audio. ASR evaluation is entirely local.
Keep generated audio outside the repository. The long fixture repeats the short
fixture for duration/memory stress ONLY; it is not independent quality evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from faster_whisper.audio import decode_audio


async def generate(output: Path, long_minutes: float) -> None:
    import edge_tts

    fixture = Path(__file__).parents[1] / "tests/fixtures/stt_roleplay.json"
    script = json.loads(fixture.read_text(encoding="utf-8"))
    assert script["synthetic"] is True
    output.mkdir(parents=True, exist_ok=True)
    voice_dir = output / "synthetic_tts"
    voice_dir.mkdir(exist_ok=True)
    semaphore = asyncio.Semaphore(2)

    async def synthesize(i: int, turn: dict) -> None:
        target = voice_dir / f"{i:03d}.mp3"
        if target.exists() and target.stat().st_size:
            return
        async with semaphore:
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(turn["text"], script["speakers"][turn["speaker"]], rate="-10%").save(str(target))
                    break
                except Exception:
                    target.unlink(missing_ok=True)
                    if attempt == 2:
                        raise RuntimeError(f"Synthetic TTS request failed for turn {i}") from None
                    await asyncio.sleep(30 * (attempt + 1))
        print(f"synthesized {i + 1}/{len(script['turns'])}", flush=True)

    await asyncio.gather(*(synthesize(i, t) for i, t in enumerate(script["turns"])))
    pieces = []
    reference = []
    cursor = 1.0
    for i, turn in enumerate(script["turns"]):
        audio = decode_audio(str(voice_dir / f"{i:03d}.mp3"), sampling_rate=16000)
        active = np.flatnonzero(np.abs(audio) > 0.003)
        if not active.size:
            raise ValueError(f"Silent TTS turn {i}")
        audio = audio[max(0, active[0] - 160):min(len(audio), active[-1] + 161)]
        start = max(0.0, cursor - turn.get("overlap_seconds", 0))
        end = start + len(audio) / 16000
        pieces.append((int(round(start * 16000)), audio * turn.get("gain", 1.0)))
        reference.append({"segment_id": f"ref-{i:03d}", "start": start, "end": end,
                          "speaker": turn["speaker"], "text": turn["text"], "terms": turn.get("terms", {}),
                          "conditions": {k: turn[k] for k in ("overlap_seconds", "gain", "gap_seconds") if k in turn}})
        cursor = end + turn.get("gap_seconds", 0.65)
    audio = np.zeros(int((cursor + 6) * 16000), dtype=np.float32)
    for start, part in pieces:
        audio[start:start + len(part)] += part
    audio = np.clip(audio, -0.98, 0.98)
    short = output / "roleplay.wav"
    sf.write(short, audio, 16000, subtype="PCM_16")
    metadata = {"synthetic": True, "provenance": "Microsoft Edge TTS; fictional checked-in script; two distinct Korean voices",
                "script_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                "audio_sha256": hashlib.sha256(short.read_bytes()).hexdigest(),
                "duration_seconds": len(audio) / 16000, "speakers": script["speakers"], "segments": reference,
                "reference_limitations": "Script reference; TTS pronunciation is not independently human-transcribed. Timing uses acoustic trim. Overlap reference is multi-label."}
    (output / "reference.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if long_minutes:
        repeats = max(1, int(np.ceil(long_minutes * 60 / metadata["duration_seconds"])))
        with sf.SoundFile(output / "stress.wav", "w", samplerate=16000, channels=1, subtype="PCM_16") as stream:
            for _ in range(repeats):
                stream.write(audio)
        long_ref = []
        for cycle in range(repeats):
            offset = cycle * metadata["duration_seconds"]
            long_ref.extend({**s, "segment_id": f"cycle-{cycle}-{s['segment_id']}", "start": s["start"] + offset, "end": s["end"] + offset} for s in reference)
        metadata.update(segments=long_ref, duration_seconds=repeats * metadata["duration_seconds"],
                        audio_sha256=hashlib.sha256((output / "stress.wav").read_bytes()).hexdigest(),
                        purpose="Repeated fixture: duration, drift, omissions and memory stress only, not independent model-selection data")
        (output / "stress-reference.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"short_seconds": len(audio) / 16000, "output": str(output)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--long-minutes", type=float, default=45)
    args = parser.parse_args()
    asyncio.run(generate(args.output, args.long_minutes))
