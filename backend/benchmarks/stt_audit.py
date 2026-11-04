"""Check chronological integrity of an actual synthetic long-audio result."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from benchmarks.stt_evaluate import evaluate


def audit(reference, short, output):
    duration = reference['duration_seconds']
    raw, turns = output['raw_segments'], output['segments']
    checks = {
        'raw_sorted': all(a['start'] <= b['start'] for a, b in zip(raw, raw[1:])),
        'turns_sorted': all(a['start'] <= b['start'] for a, b in zip(turns, turns[1:])),
        'times_in_bounds': all(0 <= s['start'] <= s['end'] <= duration + 1e-5 for s in raw + turns),
        'unique_raw_ids': len({s['segment_id'] for s in raw}) == len(raw),
        'unique_turn_ids': len({s['segment_id'] for s in turns}) == len(turns),
        'all_cores_processed': not output['failed_ranges'],
    }
    cycles = []
    for cycle in range(round(duration / short['duration_seconds'])):
        offset, limit = cycle * short['duration_seconds'], (cycle + 1) * short['duration_seconds']
        selected = [{**s, 'start': s['start'] - offset, 'end': s['end'] - offset}
                    for s in turns if offset <= (s['start'] + s['end']) / 2 < limit]
        spans = [{**s, 'start': max(s['start'], offset) - offset, 'end': min(s['end'], limit) - offset}
                 for s in output['diarization_segments'] if s['end'] > offset and s['start'] < limit]
        score = evaluate(short, {**output, 'segments': selected, 'diarization_segments': spans})
        cycles.append({'cycle': cycle + 1, 'cer': score['korean_cer'],
                       'speaker_error': score['speaker_attribution_error_on_matched_characters'],
                       'whole_turn_omissions': score['uncovered_reference_turns'],
                       'lexical_omissions': score['lexical_omission_candidates']})
    return {'duration_seconds': duration, 'reference_turns': len(reference['segments']),
            'output_turns': len(turns), 'raw_segments': len(raw), **checks,
            'passed_integrity': all(checks.values()), 'failed_ranges': output['failed_ranges'], 'cycles': cycles,
            'boundary_context': [
                {'core_boundary': t, 'turns': [{k: s[k] for k in ('segment_id', 'start', 'end', 'text')}
                                             for s in turns if s['end'] > t - 2 and s['start'] < t + 2]}
                for t in range(120, int(duration), 120)],
            'limitation': 'Repeated synthetic fixture is stress-only. Timestamp ownership and lexical alignment cannot prove zero acoustic omissions.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--short-reference', type=Path, required=True)
    parser.add_argument('--transcription', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    reference, short = read(args.reference), read(args.short_reference)
    if reference.get('synthetic') is not True or short.get('synthetic') is not True:
        raise ValueError('Only explicitly synthetic references are accepted')
    result = audit(reference, short, read(args.transcription))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if isinstance(v, (bool, int, float))}))
    if not result['passed_integrity']:
        raise SystemExit(1)
