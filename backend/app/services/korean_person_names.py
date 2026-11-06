"""Local Korean name candidates; keep in parity with the browser review rules.

Relationship/identity context establishes a name before its given-name mentions
are linked. This is deliberately not a general Korean named-entity recognizer.
"""
from __future__ import annotations

import re

COMPOUND_SURNAMES = ("남궁", "황보", "제갈", "선우", "독고", "사공", "서문", "동방")
SURNAMES = "김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경사부복태목형피두감음빈동온호"
ROLES = "친구|동료|누나|언니|오빠|형|동생|엄마|어머니|아빠|아버지|남편|아내|아들|딸|선배|후배|담임|보호자|학생|교사|교수|상담자|상담사|내담자"
STOP_WORDS = set("이야기 이렇게 이어서 이것 이상 이유 이후 이전 이름 성명 정확히 정말로 조금씩 정신과 서로 문제 고민 김치 지원 생각 수면 상담 도움 안정 학교 이번 지난 오늘 내일 아침 저녁 사실 마음 친구 누나 동생 어머니 아버지 선생님 보호자 부모님 내담자 상담자 상담사 연락처 전화번호 인적사항 가족관계".split())
AMBIGUOUS_GIVEN_NAMES = set("지원 사랑 미래 보람 지혜 수정 희망 안정 시도 시기".split())
BOUNDARY = r"(?=$|[^가-힣A-Za-z0-9_])"
PARTICLES = r"(?:에게(?:서)?|한테(?:서)?|께서|께|으로|부터|까지|처럼|보다|이라며|이라고(?:요)?|이라는|입니다|이에요|이었어요|이었고|이며|이고|인데|이요|예요|이라서|(?:씨|님)(?:은|는|이|가|을|를|의|에게|께서)?|이(?:는|가|랑|와|도|를|야|요)?|은|는|가|을|를|의|와|과|도|만|랑|로|야|아)(?:는|도|만)?"
ENDING = rf"(?=$|[^가-힣A-Za-z0-9_]|{PARTICLES}{BOUNDARY})"
FULL_NAME = rf"(?:(?:{'|'.join(COMPOUND_SURNAMES)})[가-힣]{{2}}|[{SURNAMES}][가-힣]{{2}}|[{SURNAMES}][가-힣]{{3}})"
PATTERNS = (
    rf"(?<![가-힣])(?:이름|성명)\s*(?:[:：]|은|는|이|가)\s*([가-힣]{{3}}|[가-힣]{{4}}|[가-힣]{{2}}){ENDING}",
    rf"(?<![가-힣])(?:{ROLES})(?:인)?\s+({FULL_NAME}){ENDING}",
    rf"(?<![가-힣])({FULL_NAME})(?=\s*(?:씨|님|선생님){ENDING})",
    rf"(?<![가-힣])(?:저는|제가|저|제 이름은)\s+({FULL_NAME})(?=입니다|이에요|예요|이고|이라고)",
)


def given_name(name: str) -> str:
    surname_length = 2 if name.startswith(COMPOUND_SURNAMES) and len(name) >= 4 else 1
    return name[surname_length:] if len(name) - surname_length >= 2 else ""


def name_pattern(name: str, *, exact_identity: bool = False) -> re.Pattern[str]:
    ending = ENDING
    if name in AMBIGUOUS_GIVEN_NAMES and not exact_identity:
        # "지원이가/지원 씨/지원에게" identify a person; "지원을 받았다" does not.
        ending = rf"(?=\s*(?:이(?:는|가|랑|와|도|를|야|요)|에게(?:서)?|한테(?:서)?|씨|님)(?:는|도|만)?{BOUNDARY})"
    return re.compile(rf"(?<![가-힣A-Za-z0-9_]){re.escape(name)}{ending}")


def discover_person_names(text: str, known_names=()) -> dict[str, str]:
    """Map each observed form to its full name; an empty owner means ambiguous identity."""
    full_names = list(dict.fromkeys(name.strip() for name in known_names
                                   if re.fullmatch(r"[가-힣]{2,5}", name.strip())))
    for index, pattern in enumerate(PATTERNS):
        for match in re.finditer(pattern, text):
            if re.search(r"(?:약|약물|제품|기관|진단)\s*$", text[max(0, match.start() - 12):match.start()]):
                continue
            name = match.group(1)
            ordinary_inflection = name[-1:] in "이은는을를도와과" and name[:-1] in STOP_WORDS
            if (index == 0 or (name not in STOP_WORDS and not ordinary_inflection)) and name not in full_names:
                full_names.append(name)
    result = {name: name for name in full_names if name_pattern(name, exact_identity=True).search(text)}
    for full in full_names:
        given = given_name(full)
        if given and given not in full_names and name_pattern(given).search(text):
            result[given] = full if given not in result or result[given] == full else ""
    return result


def person_replacements(text: str) -> dict[str, str]:
    names = discover_person_names(text)
    owners = list(dict.fromkeys(owner for owner in names.values() if owner))
    labels = {owner: f"인물 {chr(66 + index) if index < 25 else index + 2}" for index, owner in enumerate(owners)}
    return {name: f"[{labels[owner] if owner else '인물 확인 필요'}]" for name, owner in names.items()}


def mask_person_names(text: str) -> tuple[str, bool]:
    names = discover_person_names(text)
    replacements = person_replacements(text)
    for name in sorted(replacements, key=len, reverse=True):
        text = name_pattern(name, exact_identity=names[name] == name).sub(replacements[name], text)
    return text, bool(replacements)
