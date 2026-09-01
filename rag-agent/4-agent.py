from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


# 이 예제 폴더는 단계별 파일명 앞에 번호가 붙어 있어서
# 일반적인 import 문으로는 바로 불러오기 어렵다.
# 그래서 경로를 직접 지정해 1~3단계 모듈을 읽어온다.
DOCUMENTS = load_module("documents_demo", "1-documents.py")
sys.modules.setdefault("documents", DOCUMENTS)
EMBEDDINGS = load_module("embeddings_demo", "2-embeddings.py")
sys.modules.setdefault("embeddings", EMBEDDINGS)
LLM = load_module("llm_demo", "3-1-llm.py")
sys.modules.setdefault("llm", LLM)
RAG = load_module("rag_demo", "3-2-rag.py")


def tool_list_documents() -> str:
    """문서 목록을 조회한다.

    사용자가 "어떤 문서가 있는지", "문서 목록 보여줘"처럼 보유 문서 자체를
    확인하고 싶어할 때 이 도구를 사용한다.
    """
    docs = DOCUMENTS.load_documents()
    lines = ["[도구] 문서 목록 조회"]
    for doc in docs:
        lines.append(f"- {doc.doc_id}: {doc.text}")
    return "\n".join(lines)


def tool_document_summary() -> str:
    """보유 문서 구성을 짧게 요약한다.

    사용자가 "문서가 몇 개인지", "어떤 종류의 문서가 있는지"처럼 개요만
    궁금해할 때 이 도구를 사용한다.
    """
    docs = DOCUMENTS.load_documents()
    lines = ["[도구] 문서 구성 요약"]
    lines.append(f"- 문서 수: {len(docs)}")
    lines.append(f"- 문서 id: {', '.join(doc.doc_id for doc in docs)}")
    return "\n".join(lines)


def tool_rag(question: str) -> str:
    """문서를 검색해 근거 기반으로 답변한다.

    날씨, 지원, 환불, 정책, 고객, 주말처럼 보유 문서 내용과 직접 관련된 질문에
    이 도구를 사용한다. 문서에 없는 내용은 이 도구로 답할 수 없다.

    Args:
        question: 사용자 질문 원문.
    """
    # run_rag() 는 내부에서 문서 로드 → 임베딩 → 검색 → 답변 생성을 모두 수행한다.
    return RAG.run_rag(question, top_k=2)


def tool_direct_answer(question: str) -> str:
    """문서 검색 없이 일반 지식으로 답변한다.

    보유 문서와 무관한 일반적인 질문(인사, 상식 등)에 이 도구를 사용한다.

    Args:
        question: 사용자 질문 원문.
    """
    return LLM.generate_direct_answer(question)


TOOLS = [tool_list_documents, tool_document_summary, tool_rag, tool_direct_answer]

SYSTEM_INSTRUCTION = (
    "당신은 문서 기반 RAG 에이전트입니다. 각 도구의 설명을 참고해 질문에 가장 "
    "적합한 도구를 스스로 선택하세요. 여러 도구가 다 적절하지 않다고 판단되면 "
    "도구를 호출하지 않고 직접 답변해도 됩니다."
)


def require_gemini():
    """google.generativeai 로드 + API 키 설정 (3-1-llm.py 의 guard와 동일 패턴)."""
    if not LLM.API_KEY:
        print(
            "GEMINI_API_KEY 가 필요합니다.\n"
            "  export GEMINI_API_KEY='your-key'",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        import google.generativeai as genai
    except ImportError:
        print(
            "패키지 필요: pip install google-generativeai",
            file=sys.stderr,
        )
        sys.exit(1)
    genai.configure(api_key=LLM.API_KEY)
    return genai


def _extract_tool_name(chat) -> str:
    """chat.history 에서 실제로 호출된 함수 이름을 역추적한다.

    automatic function calling 은 도구 선택/실행/결과 반영을 SDK 내부에서
    처리하므로, 어떤 도구가 호출됐는지는 대화 이력의 function_call 파트를
    거꾸로 훑어봐야 알 수 있다. 도구를 하나도 호출하지 않았으면
    "direct_llm_response" 를 반환한다 (기존 4개 값과 구분되는 5번째 값).
    """
    for content in chat.history:
        if content.role != "model":
            continue
        for part in content.parts:
            name = part.function_call.name
            if name:
                return name
    return "direct_llm_response"


def run_agent_with_trace(question: str) -> dict[str, str]:
    """질문을 받아 LLM이 직접 도구를 고르게 하고, 선택 결과와 최종 응답을 반환한다."""
    print("=" * 60, flush=True)
    print("Agent 데모 (LLM Function Calling)", flush=True)
    print("=" * 60, flush=True)
    print(f"[입력] {question}", flush=True)

    genai = require_gemini()
    model = genai.GenerativeModel(
        model_name=LLM.CHAT_MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
        tools=TOOLS,
    )
    chat = model.start_chat(enable_automatic_function_calling=True)

    print("[계획] 규칙 기반 분기 없이 LLM이 도구 설명을 보고 직접 선택합니다.", flush=True)
    response = chat.send_message(question)
    tool_name = _extract_tool_name(chat)
    print(f"  - 선택 도구: {tool_name}", flush=True)

    print("[관찰] 도구 실행 결과가 반영된 최종 응답을 받았습니다.", flush=True)
    text = getattr(response, "text", None)
    result = text.strip() if text else f"[Gemini] 빈 응답: {response!r}"

    return {
        "question": question,
        "reason": "LLM function-calling 결정",
        "tool_name": tool_name,
        "result": result,
    }


def run_agent(question: str) -> str:
    """질문을 받아 도구를 고르고, 최종 결과 문자열만 반환한다."""
    trace = run_agent_with_trace(question)
    return trace["result"]


def main() -> None:
    """학습용 예제 질문을 순서대로 실행한다."""
    questions = [
        "문서 목록 보여줘",
        "문서 구성 요약해줘",
        "주말에 고객 지원 받을 수 있어?",
        "서울 여름 날씨는 어때?",
        "파이썬은 어떤 언어야?",
    ]

    for index, question in enumerate(questions, start=1):
        print()
        print(f"======== Agent 질문 {index} ========", flush=True)
        try:
            answer = run_agent(question)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"[오류] {exc}", file=sys.stderr, flush=True)
            sys.exit(1)
        print("--- 최종 결과 ---", flush=True)
        print(answer, flush=True)


if __name__ == "__main__":
    main()
