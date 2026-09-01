from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent


def load_module(module_name: str, file_name: str):
    """번호가 붙은 예제 파일을 경로로 직접 로드한다."""
    module_path = BASE_DIR / file_name
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# 이 예제 폴더는 단계별 파일명 앞에 번호가 붙어 있다.
# 그래서 API 파일도 필요한 모듈을 경로로 직접 읽어온다.
DOCUMENTS = load_module("documents_api", "1-documents.py")
sys.modules.setdefault("documents", DOCUMENTS)
EMBEDDINGS = load_module("embeddings_api", "2-embeddings.py")
sys.modules.setdefault("embeddings", EMBEDDINGS)
RAG = load_module("rag_api", "3-2-rag.py")
AGENT = load_module("agent_api", "4-agent.py")
AUDIT_HOOK = load_module("audit_hook_api", "audit_hook.py")

# [step-2] 감사 이벤트 수집 지점: API 계층. actor/source_ip 등 AuditEvent
# 스키마 필드가 HTTP 요청 컨텍스트와 자연스럽게 매핑된다(plan.md 참고).
RAW_EVENTS_PATH = BASE_DIR.parent / "outputs" / "raw_events" / "rag_agent_events.json"
AUDIT_CLIENT = AUDIT_HOOK.AuditEventClient(RAW_EVENTS_PATH)


def log_audit_event(
    *,
    actor: str | None,
    role: str | None,
    department: str | None,
    action: str,
    source_ip: str,
    purpose: str,
    result: str,
) -> None:
    """BackgroundTasks 에서 호출된다 — 응답을 이미 클라이언트에 보낸 뒤 실행되므로
    여기서 예외가 나도 API 응답에는 영향을 주지 않는다(감사 엔진 SPOF 제거)."""
    try:
        AUDIT_CLIENT.log(
            actor=actor or "anonymous",
            role=role or "user",
            department=department or "unknown",
            action=action,
            asset="rag-agent",
            source_ip=source_ip,
            purpose=purpose,
            result=result,
        )
    except Exception as exc:
        print(f"[audit] 로그 기록 실패: {exc}", file=sys.stderr, flush=True)


# FastAPI 앱: 지금까지 만든 문서/임베딩/RAG/Agent 기능을
# HTTP 요청으로 호출할 수 있게 감싸는 서비스 진입점이다.
app = FastAPI(
    title="RAG Agent Demo API",
    description="학습용 RAG + Agent 예제를 HTTP API로 감싼 서비스",
    version="0.1.0",
)


class QuestionRequest(BaseModel):
    # /agent 처럼 질문 문자열만 받는 엔드포인트에서 사용한다.
    question: str = Field(..., description="사용자 질문")


class RagRequest(QuestionRequest):
    # /rag 는 질문뿐 아니라 검색할 문서 개수(top_k)도 함께 받는다.
    top_k: int = Field(2, ge=1, le=10, description="검색할 상위 문서 수")


def translate_error(exc: BaseException) -> HTTPException:
    """스크립트 스타일 예외를 API용 HTTP 예외로 바꾼다."""
    if isinstance(exc, SystemExit):
        return HTTPException(status_code=500, detail="Gemini 설정 또는 실행 중 종료가 발생했습니다.")
    return HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
def health() -> dict[str, str]:
    # 서버가 살아 있는지만 빠르게 확인하는 용도
    return {"status": "ok"}


@app.get("/documents")
def get_documents() -> dict[str, object]:
    # 1-documents.py 단계에서 만든 문서 로더 결과를 그대로 보여준다.
    docs = DOCUMENTS.load_documents()
    return {
        "count": len(docs),
        "documents": [{"doc_id": doc.doc_id, "text": doc.text} for doc in docs],
    }


@app.get("/tools")
def get_tools() -> dict[str, object]:
    # 4-agent.py 가 내부에서 고를 수 있는 도구 목록을 API로 노출한다.
    return {
        "tools": [
            {"name": "tool_list_documents", "description": "문서 목록 조회"},
            {"name": "tool_document_summary", "description": "문서 구성 요약"},
            {"name": "tool_rag", "description": "RAG 검색 후 답변 생성"},
            {"name": "tool_direct_answer", "description": "문서 검색 없이 일반 답변 생성"},
        ]
    }


@app.post("/rag")
def rag_answer(
    payload: RagRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    x_actor: str | None = Header(None, alias="X-Actor"),
    x_role: str | None = Header(None, alias="X-Role"),
    x_department: str | None = Header(None, alias="X-Department"),
) -> dict[str, object]:
    # 3-rag.py 의 run_rag() 를 HTTP 엔드포인트로 감싼다.
    audit_kwargs = dict(
        actor=x_actor,
        role=x_role,
        department=x_department,
        action=AUDIT_HOOK.AuditEventClient.map_action("tool_rag"),
        source_ip=request.client.host if request.client else "unknown",
        purpose=payload.question,
    )
    try:
        answer = RAG.run_rag(payload.question, top_k=payload.top_k)
    except BaseException as exc:
        # 실패 응답은 FastAPI 예외 핸들러가 별도 Response를 생성하므로 여기서 등록한
        # BackgroundTasks는 실행되지 않는다(프레임워크 제약) — 실패 경로만 동기로 기록한다.
        log_audit_event(**audit_kwargs, result="failure")
        raise translate_error(exc) from exc

    background_tasks.add_task(log_audit_event, **audit_kwargs, result="success")
    return {
        "mode": "rag",
        "question": payload.question,
        "top_k": payload.top_k,
        "answer": answer,
    }


@app.post("/agent")
def agent_answer(
    payload: QuestionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    x_actor: str | None = Header(None, alias="X-Actor"),
    x_role: str | None = Header(None, alias="X-Role"),
    x_department: str | None = Header(None, alias="X-Department"),
) -> dict[str, object]:
    # 4-agent.py 의 run_agent_with_trace() 를 호출한다.
    # 단순 답변뿐 아니라 어떤 도구를 골랐는지도 함께 반환한다.
    tool_name = "unknown"
    try:
        trace = AGENT.run_agent_with_trace(payload.question)
        tool_name = trace["tool_name"]
    except BaseException as exc:
        # 실패 응답은 FastAPI 예외 핸들러가 별도 Response를 생성하므로 여기서 등록한
        # BackgroundTasks는 실행되지 않는다(프레임워크 제약) — 실패 경로만 동기로 기록한다.
        log_audit_event(
            actor=x_actor,
            role=x_role,
            department=x_department,
            action=AUDIT_HOOK.AuditEventClient.map_action(tool_name),
            source_ip=request.client.host if request.client else "unknown",
            purpose=payload.question,
            result="failure",
        )
        raise translate_error(exc) from exc

    background_tasks.add_task(
        log_audit_event,
        actor=x_actor,
        role=x_role,
        department=x_department,
        action=AUDIT_HOOK.AuditEventClient.map_action(tool_name),
        source_ip=request.client.host if request.client else "unknown",
        purpose=payload.question,
        result="success",
    )
    return {"mode": "agent", **trace}


if __name__ == "__main__":
    import uvicorn

    # python3 5-api.py 로 바로 실행할 수 있게 로컬 개발 서버를 띄운다.
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
