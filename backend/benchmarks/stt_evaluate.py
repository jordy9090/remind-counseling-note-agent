"""Reproducible acoustic/lexical scores, separate from human product usability.

Protected-phrase misses and silence output are review candidates, not automated
clinical judgments. Edit distance is a lower bound, never counselor editing time.
"""
from __future__ import annotations

from collections import Counter
from itertools import permutations
import re
import unicodedata


def characters(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFC", text).lower() if c.isalnum())


# Evaluation-only equivalents declared from the synthetic script, never applied
# to product transcripts. Both the strict and this alternate CER are reported.
NUMBER_EQUIVALENTS = {
    "일곱시삼십분": "7시30분", "십일월십이일": "11월12일", "오후세시": "오후3시",
    "세번째": "3번째", "네번째": "4번째", "세번": "3번", "두번": "2번", "한번": "1번", "한달": "1달",
    "네날": "4날", "영점": "0점", "십점": "10점", "육점": "6점", "팔점": "8점", "다섯시간": "5시간",
    "여섯시간": "6시간", "두시": "2시", "세시": "3시", "열세일": "13일", "한단어": "1단어", "한문장": "1문장",
}


def itn_characters(text: str) -> str:
    value = characters(text)
    for key in sorted(NUMBER_EQUIVALENTS, key=len, reverse=True):
        value = value.replace(key, NUMBER_EQUIVALENTS[key])
    return value


def _text_and_labels(segments):
    text, labels = "", []
    for s in sorted(segments, key=lambda s: (s["start"], s["end"])):
        value = characters(s["text"])
        text += value
        labels.extend([s.get("speaker") or "unknown"] * len(value))
    return text, labels


def boundary_score(reference, hypothesis, tolerance=0.5, speaker_changes_only=False):
    ref = [b["start"] for a, b in zip(reference, reference[1:]) if not speaker_changes_only or a.get("speaker") != b.get("speaker")]
    hyp = [b["start"] for a, b in zip(hypothesis, hypothesis[1:]) if not speaker_changes_only or a.get("speaker") != b.get("speaker")]
    unmatched = list(hyp)
    matched = 0
    for boundary in ref:
        if unmatched:
            nearest = min(unmatched, key=lambda x: abs(x - boundary))
            if abs(nearest - boundary) <= tolerance:
                unmatched.remove(nearest)
                matched += 1
    precision, recall = matched / max(1, len(hyp)), matched / max(1, len(ref))
    return {"precision": precision, "recall": recall, "f1": 2 * precision * recall / max(1e-9, precision + recall),
            "tolerance_seconds": tolerance, "missing_boundaries": len(ref) - matched, "extra_boundaries": len(hyp) - matched}


def diarization_error(reference, hypothesis, duration):
    import numpy as np
    ref_names = sorted({s["speaker"] for s in reference})
    hyp_names = sorted({s["speaker"] for s in hypothesis if s.get("speaker")})
    frame_seconds = 0.02
    frames = int(duration / frame_seconds) + 1
    ref = np.zeros((frames, len(ref_names)), dtype=bool)
    hyp = np.zeros((frames, len(hyp_names)), dtype=bool)
    for spans, names, matrix in ((reference, ref_names, ref), (hypothesis, hyp_names, hyp)):
        for s in spans:
            if s.get("speaker") in names:
                matrix[max(0, round(s["start"] / frame_seconds)):min(frames, round(s["end"] / frame_seconds)), names.index(s["speaker"])] = True
    target_names = ref_names + [f"unmapped_{i}" for i in range(max(0, len(hyp_names) - len(ref_names)))]
    best_mapping, best_correct = {}, -1
    for perm in permutations(target_names, len(hyp_names)):
        correct = sum(int(np.logical_and(ref[:, ref_names.index(name)], hyp[:, i]).sum()) for i, name in enumerate(perm) if name in ref_names)
        if correct > best_correct:
            best_mapping, best_correct = dict(zip(hyp_names, perm)), correct
    nref, nhyp = ref.sum(axis=1), hyp.sum(axis=1)
    miss = int(np.maximum(nref - nhyp, 0).sum())
    false_alarm = int(np.maximum(nhyp - nref, 0).sum())
    confusion = int(np.minimum(nref, nhyp).sum()) - max(0, best_correct)
    denominator = max(1, int(nref.sum()))
    return {"der": (miss + false_alarm + confusion) / denominator, "miss": miss / denominator,
            "false_alarm": false_alarm / denominator, "confusion": confusion / denominator,
            "collar_seconds": 0, "overlap_scored": True, "frame_seconds": frame_seconds, "mapping": best_mapping}


def evaluate(reference: dict, output: dict) -> dict:
    from rapidfuzz.distance import Levenshtein
    ref, hyp = reference["segments"], output["segments"]
    rtext, rlabels = _text_and_labels(ref)
    htext, hlabels = _text_and_labels(hyp)
    operations = Levenshtein.editops(rtext, htext)
    def display_text(segments):
        # Preserve punctuation and intra-turn spacing; ignore only the UI's turn
        # line breaks. Script punctuation is a reference style, not unique truth.
        return " ".join(unicodedata.normalize("NFC", s["text"]).strip()
                        for s in sorted(segments, key=lambda s: (s["start"], s["end"])))
    displayed_reference, displayed_hypothesis = display_text(ref), display_text(hyp)
    display_edits = Levenshtein.editops(displayed_reference, displayed_hypothesis)
    # A turn can overlap a hypothesis while a sentence inside it is missing.
    # Report lexical deletion runs separately from whole-turn time coverage.
    reference_positions = []
    for segment in sorted(ref, key=lambda s: (s["start"], s["end"])):
        reference_positions.extend([segment] * len(characters(segment["text"])))
    deletion_runs = []
    for tag, start, end, _, _ in Levenshtein.opcodes(rtext, htext):
        if tag == "delete" and end - start >= 4:
            affected = reference_positions[start:end]
            deletion_runs.append({"text": rtext[start:end], "characters": end - start,
                                  "start": affected[0]["start"], "end": affected[-1]["end"],
                                  "reference_ids": list(dict.fromkeys(s["segment_id"] for s in affected))})
    edits = Counter(op.tag for op in operations)
    hypothesis_positions = []
    for segment in sorted(hyp, key=lambda s: (s["start"], s["end"])):
        hypothesis_positions.extend([segment] * len(characters(segment["text"])))
    insertion_runs = []
    for tag, _, _, start, end in Levenshtein.opcodes(rtext, htext):
        if tag == "insert" and end - start >= 4:
            affected = hypothesis_positions[start:end]
            insertion_runs.append({"text": htext[start:end], "characters": end - start,
                                   "start": affected[0]["start"], "end": affected[-1]["end"],
                                   "hypothesis_ids": list(dict.fromkeys(s.get("segment_id", str(s.get("id"))) for s in affected))})
    equal = [(a + i, b + i) for tag, a, ae, b, be in Levenshtein.opcodes(rtext, htext) if tag == "equal" for i in range(ae - a)]
    hyp_names = sorted(set(hlabels))
    ref_names = sorted(set(rlabels))
    choices = ref_names + [f"unmapped_{i}" for i in range(max(0, len(hyp_names) - len(ref_names)))]
    best, mapping = -1, {}
    for perm in permutations(choices, len(hyp_names)):
        trial = dict(zip(hyp_names, perm))
        score = sum(trial.get(hlabels[j]) == rlabels[i] for i, j in equal)
        if score > best:
            best, mapping = score, trial
    protected = {}
    omissions = []
    for s in ref:
        nearby = " ".join(h["text"] for h in hyp if h["end"] > s["start"] - 0.5 and h["start"] < s["end"] + 0.5)
        if not nearby.strip():
            omissions.append({"start": s["start"], "end": s["end"], "segment_id": s["segment_id"]})
        for category, terms in s.get("terms", {}).items():
            counts = protected.setdefault(category, {"total": 0, "exact_phrase_misses": 0, "itn_equivalent_misses": 0, "candidates": []})
            for term in terms:
                counts["total"] += 1
                if characters(term) not in characters(nearby):
                    counts["exact_phrase_misses"] += 1
                    counts["candidates"].append({"segment_id": s["segment_id"], "expected": term, "observed": nearby})
                if itn_characters(term) not in itn_characters(nearby):
                    counts["itn_equivalent_misses"] += 1
    repetitions = []
    silence = []
    for i, s in enumerate(hyp):
        text = characters(s["text"])
        if i and len(text) >= 12 and text == characters(hyp[i - 1]["text"]):
            repetitions.append(s.get("segment_id", s.get("id")))
        if not any(s["end"] > r["start"] and s["start"] < r["end"] for r in ref):
            silence.append(s.get("segment_id", s.get("id")))
    boundaries = boundary_score(ref, hyp)
    speaker_turn_corrections = 0
    for h in hyp:
        overlaps = [(max(0.0, min(h["end"], r["end"]) - max(h["start"], r["start"])), r["speaker"]) for r in ref]
        amount, speaker = max(overlaps, default=(0, None))
        if amount and mapping.get(h.get("speaker") or "unknown") != speaker:
            speaker_turn_corrections += 1
    return {
        "korean_cer": len(operations) / max(1, len(rtext)), "reference_characters": len(rtext),
        "korean_cer_itn_equivalent": Levenshtein.distance(itn_characters(rtext), itn_characters(htext)) / max(1, len(itn_characters(rtext))),
        "text_edits": dict(edits), "normalization": "NFC, lowercase, punctuation/whitespace removed; ITN differences NOT silently forgiven",
        "speaker_attribution_error_on_matched_characters": (len(equal) - max(0, best)) / max(1, len(equal)),
        "matched_character_count": len(equal), "speaker_mapping": mapping,
        "diarization": diarization_error(ref, output.get("diarization_segments", []), reference["duration_seconds"]),
        "turn_boundaries": boundaries, "speaker_change_boundaries": boundary_score(ref, hyp, speaker_changes_only=True),
        "protected_phrases": protected,
        "uncovered_reference_turns": omissions, "lexical_omission_candidates": deletion_runs,
        "lexical_insertion_candidates": insertion_runs,
        "repetition_candidates": repetitions, "silence_output_candidates": silence,
        "product_proxy": {"minimum_character_edits": len(operations), "characters_to_edit_per_100_reference": len(operations) * 100 / max(1, len(rtext)),
                          "display_text_edits_including_spacing_punctuation": len(display_edits),
                          "display_text_edit_operations": dict(Counter(op.tag for op in display_edits)),
                          "display_reference_characters": len(displayed_reference),
                          "display_edit_note": "Distance to scripted reference style, including spacing/punctuation and ITN differences; not measured counselor effort.",
                          "review_flagged_turns": sum(bool(s.get("review_flags")) for s in hyp),
                          "output_turn_count": len(hyp), "coverage_review_intervals": len(output.get("review_ranges", [])),
                          "speaker_turn_corrections": speaker_turn_corrections,
                          "matched_characters_needing_speaker_reassignment": len(equal) - max(0, best),
                          "boundary_insertions": boundaries["missing_boundaries"], "boundary_deletions": boundaries["extra_boundaries"],
                          "human_correction_minutes": None, "human_reviewed": False,
                          "limitation": "Oracle edit-distance and timestamp proxies only; no counselor timing or usability claim."},
        "stage_metrics": output.get("stage_metrics", {}), "status": output.get("status"), "error_codes": output.get("error_codes", [])}
