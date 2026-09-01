"""audit_hook.py

[step-2] 감사 이벤트 수집 SDK 클라이언트.

audit-engine(AuditEvent 스키마)을 이용해 감사 이벤트를 구성하고 raw events 파일에
append 하는 얇은 클라이언트. 해시체인 검증/마스킹/암호화/보관정책 계산은 이 클라이언트의
책임이 아니다 — 별도 배치(audit-engine)가 처리한다(plan.md 흐름 A/B 분리 참고).

수집 지점(어디서 호출하는가)에 대한 가정을 갖지 않도록 순수 인터페이스로 둔다:
actor/role/department/source_ip 등은 전부 호출자(5-api.py)가 채워서 넘긴다.
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # d06
AUDIT_ENGINE_DIR = BASE_DIR / "audit-engine"

PURPOSE_MAX_LEN = 500

# 4-agent.py 도구 함수명 -> AuditEvent.action 매핑.
# step-3(LLM function calling) 전환 후 tool_name 값 집합이 이걸로 확정된다.
ACTION_MAP = {
    "tool_rag": "rag_query",
    "tool_direct_answer": "direct_answer",
    "tool_list_documents": "list_documents",
    "tool_document_summary": "document_summary",
    "direct_llm_response": "direct_llm_response",
}


def _load_audit_engine():
    """audit-engine 디렉터리명이 하이픈이라 일반 import가 불가능해 경로 로딩으로 우회한다."""
    if "audit_engine" in sys.modules:
        return sys.modules["audit_engine"]

    spec = importlib.util.spec_from_file_location(
        "audit_engine",
        AUDIT_ENGINE_DIR / "__init__.py",
        submodule_search_locations=[str(AUDIT_ENGINE_DIR)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"audit-engine 을 로드할 수 없습니다: {AUDIT_ENGINE_DIR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_engine"] = module
    spec.loader.exec_module(module)
    return module


AE = _load_audit_engine()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AuditEventClient:
    """감사 이벤트 SDK 클라이언트 — raw events 파일에 append 만 전담한다."""

    def __init__(self, raw_events_path: str | Path):
        self.raw_events_path = Path(raw_events_path)
        self.raw_events_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.raw_events_path.exists():
            self.raw_events_path.write_text("[]", encoding="utf-8")

    @staticmethod
    def map_action(tool_name: str) -> str:
        """4-agent.py 의 tool_name 을 AuditEvent.action 값으로 변환한다.
        매핑에 없는 값은 그대로 통과시킨다 — 새 action 은 audit-engine 의
        retention_policy.default_policy 로 자연스럽게 폴백된다."""
        return ACTION_MAP.get(tool_name, tool_name)

    def log(
        self,
        *,
        actor: str,
        role: str,
        department: str,
        action: str,
        asset: str,
        source_ip: str,
        purpose: str,
        result: str,
        record_id: str | None = None,
    ):
        """AuditEvent 1건을 구성해 raw events 파일에 append 하고, 구성된 이벤트를 반환한다."""
        event = AE.AuditEvent(
            timestamp=_utc_now_iso(),
            actor=actor,
            role=role,
            department=department,
            action=action,
            asset=asset,
            record_id=record_id or str(uuid.uuid4()),
            source_ip=source_ip,
            purpose=(purpose or "")[:PURPOSE_MAX_LEN],
            result=result,
        )
        self._append(event)
        return event

    def _append(self, event) -> None:
        """파일 락(fcntl.flock)을 잡고 기존 목록을 읽어 append 한 뒤 저장한다.
        동시 요청이 같은 파일에 append 할 때 서로 덮어쓰지 않도록 하기 위함이다."""
        with open(self.raw_events_path, "r+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                content = f.read()
                events = json.loads(content) if content.strip() else []
                events.append(asdict(event))
                f.seek(0)
                f.truncate()
                json.dump(events, f, ensure_ascii=False, indent=2)
                # flush 없이 언락하면 버퍼에 남은 쓰기가 파일에 반영되기 전에 다음
                # 스레드/프로세스가 락을 잡고 옛 내용을 읽어 덮어쓸 수 있다(레코드 유실).
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
