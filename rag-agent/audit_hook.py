"""audit_hook.py

[step-2, SDK 통일 리팩터] 감사 이벤트 수집 SDK.

audit_engine(AuditEvent 스키마)을 이용해 감사 이벤트를 구성하고 raw events 파일에
append 하는 얇은 SDK. 해시체인 검증/마스킹/암호화/보관정책 계산은 이 모듈의 책임이
아니다 — 별도 배치(audit_engine)가 처리한다(plan.md 흐름 A/B 분리 참고).

이전 설계는 5-api.py의 라우트 코드가 직접 로그를 남겼다 — 그래서 HTTP API를 거치지
않는 호출(CLI, 테스트, 다른 스크립트에서의 직접 import)은 감사 범위 밖이었다.
이 버전은 RAG/Agent 각 함수(run_rag, generate_direct_answer, tool_*,
run_agent_with_trace)가 자기 실행 결과를 스스로 log_event() 로 기록한다 — 호출
경로와 무관하게 항상 감사가 남는다.

actor/role/department/source_ip 처럼 "누가/어디서" 호출했는지는 호출자마다 다르고,
그 정보가 있는 곳(HTTP 요청)과 실제 로깅이 필요한 곳(RAG/Agent 함수 내부, 몇 단계
아래) 사이에 거리가 있다. 이걸 매 함수 시그니처에 파라미터로 꿰어 넣는 대신
contextvars로 전파한다 — 요청 시작 시점에 set_context() 로 한 번 심어두면, 이후
몇 단계를 거쳐 호출되는 어떤 함수에서 log_event() 를 불러도 자동으로 그 값을 쓴다.
OpenTelemetry/Sentry 같은 관측 SDK가 요청 컨텍스트를 전파하는 것과 같은 방식이다.
"""

from __future__ import annotations

import contextvars
import fcntl
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # d06

# audit_engine 이 d06 바로 아래의 정규 패키지(언더스코어 이름)라 일반 import로 충분하다.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
import audit_engine as AE  # noqa: E402

PURPOSE_MAX_LEN = 500
DEFAULT_RAW_EVENTS_PATH = BASE_DIR / "outputs" / "raw_events" / "rag_agent_events.json"


@dataclass(frozen=True)
class AuditContext:
    """요청마다 달라지는 "누가/어디서" 값. 아무도 설정하지 않으면(CLI 등) 이 기본값이 쓰인다."""

    actor: str = "anonymous"
    role: str = "user"
    department: str = "unknown"
    source_ip: str = "local"


_current_context: "contextvars.ContextVar[AuditContext]" = contextvars.ContextVar(
    "audit_hook_context", default=AuditContext()
)


def set_context(ctx: AuditContext):
    """현재 컨텍스트(동기 호출 체인 전체)에 감사 컨텍스트를 심는다.
    반환값을 reset_context() 에 넘기면 이전 상태로 복원할 수 있다."""
    return _current_context.set(ctx)


def reset_context(token) -> None:
    _current_context.reset(token)


def current_context() -> AuditContext:
    return _current_context.get()


# run_agent_with_trace() 처럼 "하위 호출(도구)이 이미 감사를 기록했는지" 알아야
# 중복 기록 없이 폴백 로깅을 할 수 있는 지점을 위한 추적 플래그.
# (예: chat.send_message() 자체가 도구 실행 전에 실패하면 아무 도구도 log_event()를
#  안 불렀을 테니 폴백이 기록해야 하고, 도구가 실행되다 실패했으면 그 도구가 이미
#  기록했을 테니 폴백은 기록하지 않아야 한다.)
_event_logged: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "audit_hook_event_logged", default=False
)


def begin_tracking():
    """이 시점 이후 log_event() 호출 여부 추적을 시작한다. 반환값을 end_tracking()에 넘겨 복원."""
    return _event_logged.set(False)


def end_tracking(token) -> None:
    _event_logged.reset(token)


def was_logged() -> bool:
    """begin_tracking() 이후 log_event()가 (성공/실패 결과와 무관하게) 호출된 적 있는지."""
    return _event_logged.get()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AuditEventClient:
    """감사 이벤트 파일 클라이언트 — raw events 파일에 append 만 전담한다."""

    def __init__(self, raw_events_path: str | Path):
        self.raw_events_path = Path(raw_events_path)
        self.raw_events_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.raw_events_path.exists():
            self.raw_events_path.write_text("[]", encoding="utf-8")

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


_default_client: AuditEventClient | None = None


def _get_default_client() -> AuditEventClient:
    global _default_client
    if _default_client is None:
        _default_client = AuditEventClient(DEFAULT_RAW_EVENTS_PATH)
    return _default_client


def log_event(*, action: str, purpose: str, result: str, asset: str = "rag-agent") -> None:
    """현재 컨텍스트(set_context 로 심어둔 값, 없으면 기본 placeholder)로 감사 이벤트
    1건을 기록한다. 호출하는 쪽(RAG/Agent 함수)은 자신이 HTTP API를 통해 실행됐는지,
    CLI로 직접 실행됐는지 몰라도 된다 — 그게 이 함수를 SDK 계층에 두는 이유다.

    감사 기록 실패는 예외로 올리지 않는다 — 감사 엔진 장애가 RAG 응답을 막으면
    안 된다는 원칙(plan.md step-2 구조 결정 1번)이 여기서도 적용된다.
    """
    ctx = current_context()
    _event_logged.set(True)  # 기록 시도 자체를 표시 (파일 쓰기 성공 여부와 무관)
    try:
        _get_default_client().log(
            actor=ctx.actor,
            role=ctx.role,
            department=ctx.department,
            action=action,
            asset=asset,
            source_ip=ctx.source_ip,
            purpose=purpose,
            result=result,
        )
    except Exception as exc:
        print(f"[audit] 로그 기록 실패: {exc}", file=sys.stderr, flush=True)
