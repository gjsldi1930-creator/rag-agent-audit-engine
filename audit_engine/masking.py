"""
[Audit Engine] PII 탐지/마스킹 및 비식별화 유틸
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
정규표현식 기반 PII 탐지(email/phone/rrn/card)와 문맥 기반 이름 마스킹, 그리고
가명처리/익명화 유틸을 제공한다 (Ch03/d03의 lab05 비식별화 + lab06 마스킹 로직을
d03 파일 import 없이 독립 재구현).

마스킹은 완전 치환([RRN_MASKED]) 대신, 일부 자릿수만 남기고 나머지를 '*'로 가리는
부분 마스킹 방식을 사용한다 (예: 991111-1234567 -> 991111-1******). 형식 검증이나
가독성이 필요한 실무 화면에 가깝고, 남은 '*' 문자가 원래의 숫자/문자 패턴을 깨뜨리므로
마스킹 후에는 원본 정규식으로 다시 탐지되지 않는다.
"""

import hashlib
import re

REGEX_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"01[0-9]-\d{3,4}-\d{4}"),
    "rrn": re.compile(r"\d{6}-\d{7}"),
    "card": re.compile(r"\d{4}-\d{4}-\d{4}-\d{4}"),
}

# "저는 김민수", "박서연 고객"처럼 이름 앞뒤 문맥이 뚜렷한 경우만 잡는 간이 규칙
NAME_CONTEXT_PATTERNS = [
    (re.compile(r"(저는\s*)([가-힣]{2,4})"), 2),
    (re.compile(r"([가-힣]{2,4})(님)"), 1),
    (re.compile(r"([가-힣]{2,4})(\s*고객)"), 1),
]


def mask_rrn(value: str) -> str:
    """991111-1234567 -> 991111-1******"""
    front, sep, back = value.partition("-")
    if not sep or not back:
        return "*" * len(value)
    return f"{front}-{back[0]}{'*' * (len(back) - 1)}"


def mask_phone(value: str) -> str:
    """010-1234-5678 -> 010-****-5678"""
    parts = value.split("-")
    if len(parts) != 3:
        return "*" * len(value)
    parts[1] = "*" * len(parts[1])
    return "-".join(parts)


def mask_card(value: str) -> str:
    """1234-5678-9012-3456 -> 1234-****-****-3456"""
    parts = value.split("-")
    if len(parts) != 4:
        return "*" * len(value)
    parts[1] = "*" * len(parts[1])
    parts[2] = "*" * len(parts[2])
    return "-".join(parts)


def mask_email(value: str) -> str:
    """test@example.com -> te**@example.com"""
    local, sep, domain = value.partition("@")
    if not sep:
        return "*" * len(value)
    keep = min(2, max(len(local) - 1, 0)) or 1
    masked_local = local[:keep] + "*" * (len(local) - keep)
    return f"{masked_local}@{domain}"


def mask_name(value: str) -> str:
    """김민수 -> 김*수, 김민 -> 김*"""
    if len(value) <= 1:
        return "*" * len(value)
    if len(value) == 2:
        return value[0] + "*"
    return value[0] + "*" * (len(value) - 2) + value[-1]


MASK_FUNCTIONS = {
    "email": mask_email,
    "phone": mask_phone,
    "rrn": mask_rrn,
    "card": mask_card,
    "name": mask_name,
}


def apply_regex_masking(text: str) -> tuple[str, list[tuple[str, str]]]:
    """이메일/전화번호/주민번호/카드번호 형식을 탐지해 부분 마스킹"""
    masked_text = text
    findings = []

    for label, pattern in REGEX_PATTERNS.items():
        matches = pattern.findall(masked_text)
        if not matches:
            continue
        findings.extend((label, match) for match in matches)
        mask_fn = MASK_FUNCTIONS[label]
        masked_text = pattern.sub(lambda m, fn=mask_fn: fn(m.group(0)), masked_text)

    return masked_text, findings


def apply_name_context_masking(text: str) -> tuple[str, list[tuple[str, str]]]:
    """형식이 없는 이름을 문맥 기반 규칙으로 탐지해 부분 마스킹"""
    masked_text = text
    findings = []

    for pattern, group_index in NAME_CONTEXT_PATTERNS:
        while True:
            match = pattern.search(masked_text)
            if not match:
                break
            candidate = match.group(group_index)
            findings.append(("name", candidate))
            start, end = match.span(group_index)
            masked_text = masked_text[:start] + mask_name(candidate) + masked_text[end:]

    return masked_text, findings


def mask_text(text: str) -> tuple[str, list[tuple[str, str]]]:
    """정규식 기반 PII 마스킹 후 문맥 기반 이름 마스킹을 순차 적용"""
    if not text:
        return text, []
    regex_masked, regex_findings = apply_regex_masking(text)
    name_masked, name_findings = apply_name_context_masking(regex_masked)
    return name_masked, regex_findings + name_findings


def pseudonymize_actor(actor: str) -> str:
    """가명처리: 원본 식별자 대신 해시 조각으로 대체 (같은 actor는 같은 토큰 -> 추적 가능성 유지)"""
    if not actor:
        return actor
    digest = hashlib.sha256(actor.encode("utf-8")).hexdigest()[:10]
    return f"ACTOR-{digest}"


def anonymize_department(department: str) -> str:
    """익명화: 세부 하위 조직명 대신 상위 범주만 남김 (예: 'platform-security' -> 'platform')"""
    if not department:
        return department
    return department.split("-")[0]
