"""
[Audit Engine] 파이프라인 단계별 중간 검증
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
`inspect()`가 만든 결과를 신뢰하지 않고, 해시체인/마스킹·가명처리/암호화/보관정책 4단계
각각이 실제로 올바르게 수행됐는지 별도 코드로 재검사한다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .crypto import KeyNotFoundError, KeyVault, decrypt_data
from .masking import REGEX_PATTERNS


@dataclass(frozen=True)
class CheckResult:
    stage: str
    passed: bool
    detail: str


def check_hash_chain(report: dict) -> CheckResult:
    """1단계: 해시체인 무결성 검증 결과를 재확인"""
    chain = report["hash_chain"]
    if chain["valid"]:
        return CheckResult("hash_chain", True, f"{report['event_count']}개 엔트리 무결성 정상")
    return CheckResult(
        "hash_chain", False,
        f"엔트리 #{chain['failed_index']}에서 위변조 감지 (사유: {chain['failure_reason']})",
    )


def check_masking(records: list) -> CheckResult:
    """2단계: 마스킹 처리 후에도 원본 PII 패턴이 남아있는지 재탐지"""
    leaked = []
    for r in records:
        for label, pattern in REGEX_PATTERNS.items():
            if pattern.search(r.masked_purpose):
                leaked.append(f"{r.event.record_id}({label})")

    if not leaked:
        return CheckResult("masking", True, f"{len(records)}개 레코드 모두 원본 PII 잔존 없음")
    return CheckResult("masking", False, f"마스킹 후에도 PII 잔존: {', '.join(leaked)}")


def check_encryption(records: list, vault: KeyVault) -> CheckResult:
    """3단계: 암호문을 실제로 복호화해 마스킹/가명처리된 값과 일치하는지 라운드트립 검증"""
    mismatches = []
    for r in records:
        data_id = r.encrypted_payload["data_id"]
        try:
            key = vault.get_key(data_id)
        except KeyNotFoundError:
            mismatches.append(f"{r.event.record_id}(키 없음)")
            continue

        decrypted = decrypt_data(r.encrypted_payload, key)
        if r.pseudonymized_actor not in decrypted or r.masked_purpose not in decrypted:
            mismatches.append(f"{r.event.record_id}(불일치)")

    if not mismatches:
        return CheckResult("encryption", True, f"{len(records)}개 레코드 모두 복호화 라운드트립 일치")
    return CheckResult("encryption", False, f"암호화 라운드트립 실패: {', '.join(mismatches)}")


def check_retention(records: list) -> CheckResult:
    """4단계: 보관 만료일을 이벤트 시각 + 보관일수로 재계산해 저장된 값과 대조"""
    mismatches = []
    for r in records:
        ts_clean = r.event.timestamp.replace("Z", "+00:00")
        try:
            event_dt = datetime.fromisoformat(ts_clean)
        except ValueError:
            continue

        expected_until = (event_dt + timedelta(days=r.retention_days)).strftime("%Y-%m-%d")
        if expected_until != r.retention_until:
            mismatches.append(r.event.record_id)

    if not mismatches:
        return CheckResult("retention", True, f"{len(records)}개 레코드 모두 만료일 계산 일치")
    return CheckResult("retention", False, f"보관 만료일 재계산 불일치: {', '.join(mismatches)}")


def run_verification(report: dict, vault: KeyVault) -> list[CheckResult]:
    """4단계 검증을 순서대로 실행"""
    records = report["records"]
    return [
        check_hash_chain(report),
        check_masking(records),
        check_encryption(records, vault),
        check_retention(records),
    ]
