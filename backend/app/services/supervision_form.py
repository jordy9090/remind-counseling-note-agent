"""Presentation of the repository's 2021-09-11 KCPA supervision form.

Stable section/block identifiers stay unchanged so saved reports remain editable.
The scan's C-1 table has two columns, including attendance and supervision events.
"""
import re


def form_heading(title: str) -> str:
    return re.sub(r"^[ABC]-(\d+)\.", r"\1.", title)


def progress_form_rows(rows: list[dict]) -> list[dict[str, str]]:
    result = []
    for row in rows:
        if "날짜(소요시간)" in row:
            result.append({"날짜(소요시간)": row["날짜(소요시간)"], "회기 주제": row.get("회기 주제", ""),
                           **{key: value for key, value in row.items() if key not in {"날짜(소요시간)", "회기 주제"}}})
            continue
        if not any(key in row for key in ("상담일", "회기", "소요시간", "이전 수퍼비전")):
            result.append(row.copy())
            continue
        def value(key):
            text = str(row.get(key) or "").strip()
            return "" if text == "[상담사 확인 필요]" else text
        date = " ".join(value(key) for key in ("회기", "상담일") if value(key) not in ("", "-"))
        if value("소요시간") not in ("", "-"):
            date += f" ({value('소요시간')})"
        topic = "\n".join(value(key) for key in ("회기 주제", "취소·지각·결석", "이전 수퍼비전")
                          if value(key) not in ("", "-", "상담"))
        # Preserve any counselor-added columns in older drafts as labeled text.
        extras = [f"{key}: {val}" for key, val in row.items()
                  if key not in {"회기", "상담일", "소요시간", "회기 주제", "취소·지각·결석", "이전 수퍼비전"} and val]
        result.append({"날짜(소요시간)": date, "회기 주제": "\n".join([topic, *extras]).strip()})
    return result
