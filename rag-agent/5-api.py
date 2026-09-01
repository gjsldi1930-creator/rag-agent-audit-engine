from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
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

# audit_hook 은 번호 없는 정상 파일명이라 일반 import로 충분하다. RAG/AGENT가 내부에서
# 이미 각자 import audit_hook 을 했으므로 sys.modules에 캐시된 동일 인스턴스를 그대로 쓴다
# (import는 멱등 — 매번 새로 실행되지 않고 캐시를 재사용한다). 감사 로깅 자체는 이제
# RAG/AGENT 내부(SDK 계층)에서 스스로 수행한다 — 여기서는 "누가/어디서" 컨텍스트만 심어준다.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
import audit_hook  # noqa: E402

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


def _build_audit_context(
    request: Request,
    x_actor: str | None,
    x_role: str | None,
    x_department: str | None,
) -> audit_hook.AuditContext:
    return audit_hook.AuditContext(
        actor=x_actor or "anonymous",
        role=x_role or "user",
        department=x_department or "unknown",
        source_ip=request.client.host if request.client else "unknown",
    )


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
    x_actor: str | None = Header(None, alias="X-Actor"),
    x_role: str | None = Header(None, alias="X-Role"),
    x_department: str | None = Header(None, alias="X-Department"),
) -> dict[str, object]:
    # 3-2-rag.py 의 run_rag() 를 HTTP 엔드포인트로 감싼다.
    # 감사 로깅은 run_rag() 내부(SDK 계층)에서 스스로 수행한다 — 여기서는 이 요청의
    # actor/source_ip 컨텍스트만 심어주고, 실제 기록 여부/시점은 run_rag()가 결정한다.
    token = audit_hook.set_context(_build_audit_context(request, x_actor, x_role, x_department))
    try:
        answer = RAG.run_rag(payload.question, top_k=payload.top_k)
    except BaseException as exc:
        raise translate_error(exc) from exc
    finally:
        audit_hook.reset_context(token)
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
    x_actor: str | None = Header(None, alias="X-Actor"),
    x_role: str | None = Header(None, alias="X-Role"),
    x_department: str | None = Header(None, alias="X-Department"),
) -> dict[str, object]:
    # 4-agent.py 의 run_agent_with_trace() 를 호출한다.
    # 감사 로깅은 실행된 도구(또는 도구 미실행 시 run_agent_with_trace 자신)가
    # SDK 계층에서 스스로 수행한다 — 여기서는 컨텍스트만 심어준다.
    token = audit_hook.set_context(_build_audit_context(request, x_actor, x_role, x_department))
    try:
        trace = AGENT.run_agent_with_trace(payload.question)
    except BaseException as exc:
        raise translate_error(exc) from exc
    finally:
        audit_hook.reset_context(token)
    return {"mode": "agent", **trace}


if __name__ == "__main__":
    import uvicorn

    # python3 5-api.py 로 바로 실행할 수 있게 로컬 개발 서버를 띄운다.
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
