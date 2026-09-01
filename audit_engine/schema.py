"""
[Audit Engine] 감사 이벤트 스키마 및 로그 파일 로더
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
기존 lab10_step0*.py 소스에 의존하지 않는 독립 스키마 정의.
raw events 파일과 hash-chain 결과 파일(둘 다 이벤트 딕셔너리를 포함) 두 포맷을 자동 판별하여
AuditEvent 리스트로 변환한다.
"""

from dataclasses import dataclass
import json
import os


@dataclass(frozen=True)
class AuditEvent:
    timestamp: str    # When (UTC)
    actor: str        # Who (사용자/시스템 식별자)
    role: str         # Who (권한/역할)
    department: str   # Who (소속 부서)
    action: str       # How (수행 행위)
    asset: str        # What (대상 자산)
    record_id: str    # What (대상 레코드 ID)
    source_ip: str    # Where (접속 IP)
    purpose: str      # Why (작업 목적/사유)
    result: str       # Result (성공/실패/거부)


def load_events_from_file(filepath: str) -> list[AuditEvent]:
    """raw events JSON 또는 hash-chain 결과 JSON을 자동 판별하여 AuditEvent 목록으로 로드"""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"로그 파일을 찾을 수 없습니다: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    if not isinstance(raw_json, list):
        raise ValueError(f"지원하지 않는 로그 파일 형식입니다 (list 형식 필요): {filepath}")

    events = []
    for item in raw_json:
        if not isinstance(item, dict):
            continue
        event_dict = item["event"] if "event" in item else item
        events.append(AuditEvent(**event_dict))
    return events
