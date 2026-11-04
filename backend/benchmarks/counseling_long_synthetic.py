"""Synthesize the fixed fictional long-session script, never real counseling text."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import numpy as np
import soundfile as sf
from faster_whisper.audio import decode_audio


async def generate(output: Path) -> None:
    import edge_tts
    fixture = Path(__file__).parents[1] / 'tests/fixtures/counseling_long_v3.json'
    script = json.loads(fixture.read_text(encoding='utf-8'))
    assert script['id'] == 'synthetic-ko-long-v3' and script['synthetic'] is True
    output.mkdir(parents=True, exist_ok=True)
    cache = output/'tts'
    cache.mkdir(exist_ok=True)
    gate = asyncio.Semaphore(3)
    async def synthesize(index, turn):
        digest = hashlib.sha256((turn['text']+script['speakers'][turn['speaker']]).encode()).hexdigest()[:12]
        target = cache/f'{index:03d}-{digest}.mp3'
        async with gate:
            if not target.exists() or not target.stat().st_size:
                for attempt in range(3):
                    try:
                        await edge_tts.Communicate(turn['text'], script['speakers'][turn['speaker']], rate='+0%').save(str(target))
                        break
                    except Exception:
                        target.unlink(missing_ok=True)
                        if attempt == 2: raise RuntimeError(f'Synthetic TTS failed at turn {index}') from None
                        await asyncio.sleep(15*(attempt+1))
            print(json.dumps({'tts_turn':index,'of':len(script['turns'])}),flush=True)
        return target
    files = await asyncio.gather(*(synthesize(i,t) for i,t in enumerate(script['turns'])))
    parts, reference, cursor = [], [], 1.0
    for i,(turn,path) in enumerate(zip(script['turns'], files)):
        audio = decode_audio(str(path),sampling_rate=16000)
        active = np.flatnonzero(np.abs(audio)>0.003)
        if not active.size: raise RuntimeError(f'No synthetic speech at {i}')
        audio=audio[max(0,active[0]-160):min(len(audio),active[-1]+161)]
        start=max(0,cursor-turn.get('overlap_seconds',0)); end=start+len(audio)/16000
        parts.append((round(start*16000),audio*turn.get('gain',1)))
        reference.append({'segment_id':f'ref-{i:03d}','speaker':turn['speaker'],'start':start,'end':end,'text':turn['text'],'chapter':turn['chapter'],'conditions':{k:turn[k] for k in ['gain','overlap_seconds','gap_seconds'] if k in turn}})
        cursor=end+turn.get('gap_seconds',0.8)
    duration=cursor+2
    if not 2400 <= duration <= 3600:
        (output/'duration-out-of-range.json').write_text(json.dumps({'seconds':duration}))
        raise ValueError(f'Natural synthesis duration outside 40–60 minutes: {duration}')
    mixed=np.zeros(round(duration*16000),dtype=np.float32)
    for start,audio in parts: mixed[start:start+len(audio)]+=audio
    target=output/'counseling-long.wav'
    sf.write(target,np.clip(mixed,-0.98,0.98),16000,subtype='PCM_16')
    metadata={'synthetic':True,'provenance':'Fictional fixed script; Microsoft Edge TTS receives synthetic text only; no repeated audio loop, no time stretching','speakers':script['speakers'],'duration_seconds':duration,'script_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'audio_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'characters':sum(len(t['text']) for t in script['turns']),'unique_turn_texts':len(set(t['text'] for t in script['turns'])),'segments':reference,'reference_limitations':'Script reference, not independent human transcription; acoustic trimming for timing, synthetic voices are not natural counseling.'}
    (output/'reference.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'completed':True,'duration_seconds':duration,'turns':len(reference),'audio_sha256':metadata['audio_sha256']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    asyncio.run(generate(parser.parse_args().output))
