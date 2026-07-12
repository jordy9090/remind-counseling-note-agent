"""Convert raw counseling datasets into a unified intermediate format.

Intermediate record (one JSON object per line in data/processed/intermediate_<source>.jsonl):

{
  "id": "kmi-1",
  "source": "kmi",                # kmi | cactus | cpsycoun | aihub_71806
  "lang": "ko",                   # ko | en | zh
  "license": "CC-BY-4.0",
  "dialogue": [{"speaker": "counselor"|"client", "text": "...", "label": "..."|null}],
  "meta": {...},                  # source-specific extras (intake form, CBT plan, MI labels...)
  "note": null | {SessionSummaryDraft-shaped dict}
}

`note` is the SFT target. Sources that ship no session note (KMI, CPsyCoun) leave it
null; data/synthesize_notes.py fills it with an LLM. CACTUS notes are derived
rule-based from its intake_form / cbt_plan fields (English, auxiliary format data).

Usage:
  python data/convert.py --source all
  python data/convert.py --source kmi
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RAW = Path(__file__).parent / "raw"
OUT = Path(__file__).parent / "processed"

REVIEW_TYPES = {"inferred", "model_inference", "needs_review", "counselor_input", "prior_context_based"}


def section(text: str, evidence_type: str = "direct", source_refs: list[str] | None = None) -> dict:
    return {
        "text": text,
        "evidence_type": evidence_type,
        "source_refs": ["transcript_text"] if source_refs is None else source_refs,
        "requires_review": evidence_type in REVIEW_TYPES,
    }


REFLECTION_PLACEHOLDER_KO = "상담자 reflection은 상담사가 직접 작성하거나 확인해야 합니다."
REFLECTION_PLACEHOLDER_EN = "Counselor reflection must be written or confirmed by the counselor."


# ---------------------------------------------------------------- KMI (Korean)

def convert_kmi() -> list[dict]:
    data = json.loads((RAW / "KMI" / "kmi.json").read_text(encoding="utf-8"))
    records = []
    for item in data:
        dialogue = [
            {
                "speaker": "counselor" if turn["role"] == "Therapist" else "client",
                "text": turn["utterance_ko"].strip(),
                "label": turn.get("label"),
            }
            for turn in item["dialogue"]
        ]
        records.append(
            {
                "id": f"kmi-{item['id']}",
                "source": "kmi",
                "lang": "ko",
                "license": "CC-BY-4.0",
                "dialogue": dialogue,
                "meta": {
                    "category_ko": item.get("category_ko", ""),
                    "mi_labels": sorted({t["label"] for t in item["dialogue"] if t.get("label")}),
                },
                "note": None,  # filled by synthesize_notes.py
            }
        )
    return records


# ------------------------------------------------------------- CACTUS (English)

INTAKE_SECTION_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
NEXT_PLAN_EN_RE = re.compile(r"\b(next session|homework|between now|practice|next time|next week)\b", re.I)

ATTITUDE_SENTENCE = {
    "positive": "The client engaged openly and responded receptively to the counselor's interventions.",
    "neutral": "The client engaged with the session while remaining reserved about some interventions.",
    "negative": "The client expressed skepticism or resistance toward parts of the counselor's interventions.",
}


def _intake_sections(intake_form: str) -> dict[str, str]:
    """Split the CACTUS intake form into numbered sections keyed by heading."""
    sections: dict[str, list[str]] = {}
    current = "header"
    for line in intake_form.splitlines():
        match = INTAKE_SECTION_RE.match(line)
        if match:
            current = match.group(1).strip().lower()
            sections[current] = []
        else:
            sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_script_dialogue(script: str, counselor_prefixes: tuple[str, ...], client_prefixes: tuple[str, ...]) -> list[dict]:
    turns: list[dict] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        speaker = None
        for prefix in counselor_prefixes:
            if stripped.startswith(prefix):
                speaker, text = "counselor", stripped[len(prefix):].strip()
                break
        if speaker is None:
            for prefix in client_prefixes:
                if stripped.startswith(prefix):
                    speaker, text = "client", stripped[len(prefix):].strip()
                    break
        if speaker is None:
            if turns:  # continuation of the previous turn
                turns[-1]["text"] += " " + stripped
            continue
        turns.append({"speaker": speaker, "text": text, "label": None})
    return turns


def _first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(parts[:n]).strip()


def _cactus_note(item: dict, dialogue: list[dict]) -> dict:
    intake = _intake_sections(item["intake_form"])
    presenting = intake.get("presenting problem", "").strip() or item.get("thought", "")
    technique = item.get("cbt_technique") or "CBT-based intervention"

    plan_steps = re.findall(r"^\d+\.\s+(.+)$", item.get("cbt_plan", ""), re.M)
    intervention = (
        f"The counselor applied {technique}. " + " ".join(plan_steps[:2])
        if plan_steps
        else f"The counselor applied {technique}."
    )

    next_plan_line = next(
        (t["text"] for t in reversed(dialogue) if t["speaker"] == "counselor" and NEXT_PLAN_EN_RE.search(t["text"])),
        None,
    )
    next_plan = (
        section(_first_sentences(next_plan_line, 2))
        if next_plan_line
        else section("No explicit next-session plan was stated; the counselor should confirm.", "needs_review", [])
    )

    session_content = (
        f"In this session the counselor used {technique} to address the client's concern: "
        f"{_first_sentences(presenting, 2)}"
    )

    return {
        "session_theme": section(f"Session theme: {technique} for the client's presenting concern.", "mixed"),
        "presenting_problem": section(_first_sentences(presenting, 3)),
        "session_content": section(session_content, "mixed"),
        "counselor_intervention": section(_first_sentences(intervention, 3)),
        "client_response": section(ATTITUDE_SENTENCE.get(item.get("attitude", ""), ATTITUDE_SENTENCE["neutral"]), "inferred"),
        "reflection": section(REFLECTION_PLACEHOLDER_EN, "counselor_input", []),
        "next_plan": next_plan,
    }


def convert_cactus(limit: int | None = None) -> list[dict]:
    data = json.loads((RAW / "cactus.json").read_text(encoding="utf-8"))
    if limit:
        data = data[:limit]
    records = []
    for i, item in enumerate(data):
        dialogue = _parse_script_dialogue(item["dialogue"], ("Counselor:",), ("Client:",))
        if len(dialogue) < 4:
            continue
        records.append(
            {
                "id": f"cactus-{i}",
                "source": "cactus",
                "lang": "en",
                "license": "MIT",
                "dialogue": dialogue,
                "meta": {
                    "cbt_technique": item.get("cbt_technique", ""),
                    "attitude": item.get("attitude", ""),
                    "patterns": item.get("patterns", []),
                },
                "note": _cactus_note(item, dialogue),
            }
        )
    return records


# ---------------------------------------------------------- CPsyCounD (Chinese)

def convert_cpsycoun() -> list[dict]:
    data = json.loads((RAW / "CPsyCounD.json").read_text(encoding="utf-8"))
    records = []
    for i, item in enumerate(data):
        dialogue: list[dict] = []
        for client_turn, counselor_turn in item.get("history", []):
            dialogue.append({"speaker": "client", "text": client_turn.strip(), "label": None})
            dialogue.append({"speaker": "counselor", "text": counselor_turn.strip(), "label": None})
        if item.get("instruction"):
            dialogue.append({"speaker": "client", "text": item["instruction"].strip(), "label": None})
        if item.get("output"):
            dialogue.append({"speaker": "counselor", "text": item["output"].strip(), "label": None})
        if len(dialogue) < 4:
            continue
        records.append(
            {
                "id": f"cpsycoun-{i}",
                "source": "cpsycoun",
                "lang": "zh",
                "license": "CC-BY-SA-4.0",
                "dialogue": dialogue,
                "meta": {},
                "note": None,
            }
        )
    return records


# ----------------------------------------------------------------------- main

CONVERTERS = {"kmi": convert_kmi, "cactus": convert_cactus, "cpsycoun": convert_cpsycoun}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="all", choices=["all", *CONVERTERS])
    parser.add_argument("--cactus-limit", type=int, default=None, help="cap CACTUS records (31,577 total)")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    sources = list(CONVERTERS) if args.source == "all" else [args.source]
    for source in sources:
        records = CONVERTERS[source](args.cactus_limit) if source == "cactus" else CONVERTERS[source]()
        path = OUT / f"intermediate_{source}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        with_note = sum(1 for r in records if r["note"])
        print(f"{source}: {len(records)} records ({with_note} with notes) -> {path}")


if __name__ == "__main__":
    main()
