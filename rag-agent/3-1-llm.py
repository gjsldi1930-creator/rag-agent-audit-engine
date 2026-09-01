"""3-1-llm.py

Gemini LLM 호출만 담당하는 단계.
3-2-rag.py 는 RAG 답변 생성에 이 파일을 쓰고,
4-agent.py 는 일반 답변 생성에 이 파일을 쓴다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
import audit_hook  # noqa: E402

# GEMINI_API_KEY 만 사용 (없으면 종료). 교육용으로 다른 프로바이더는 넣지 않음.
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# 답변 생성 모델
CHAT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# RAG 답변 생성 시 넣는 시스템 지시문
SYSTEM_INSTRUCTION = (
    "당신은 RAG 어시스턴트입니다. "
    "제공된 Context 범위 안에서만 한국어로 간결히 답합니다."
)


def require_gemini():
    """google.generativeai 로드 + API 키 설정."""
    if not API_KEY:
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
    genai.configure(api_key=API_KEY)
    return genai


def generate_answer(genai, user_prompt: str) -> str:
    """Prompt → Gemini → 답변 문자열."""
    print(f"[6] LLM 호출 model={CHAT_MODEL}", flush=True)
    model = genai.GenerativeModel(
        model_name=CHAT_MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
    )
    response = model.generate_content(
        user_prompt,
        generation_config={"temperature": 0.2},
    )
    text = getattr(response, "text", None)
    if not text:
        return f"[Gemini] 빈 응답: {response!r}"
    return text.strip()


def generate_direct_answer(question: str) -> str:
    """문서 검색 없이 질문만으로 일반 답변을 생성한다.

    이 함수가 호출 결과를 스스로 감사 로그에 남긴다(action="direct_answer") — 호출자가
    HTTP API인지 CLI인지 몰라도 된다. actor/source_ip 등은 audit_hook.set_context()로
    미리 심어둔 값을 쓰고, 아무도 심어두지 않았으면(CLI 등) 기본 placeholder를 쓴다.
    """
    try:
        genai = require_gemini()
        model = genai.GenerativeModel(
            model_name=CHAT_MODEL,
            system_instruction=(
                "당신은 간단한 학습용 에이전트입니다. "
                "도구 결과가 없을 때는 한국어로 짧고 분명하게 답하세요."
            ),
        )
        response = model.generate_content(
            question,
            generation_config={"temperature": 0.2},
        )
        text = getattr(response, "text", None)
        result = text.strip() if text else f"[Gemini] 빈 응답: {response!r}"
    except BaseException:
        audit_hook.log_event(action="direct_answer", purpose=question, result="failure")
        raise
    audit_hook.log_event(action="direct_answer", purpose=question, result="success")
    return result

if __name__ == "__main__":
    # 단독 테스트 실행
    test_question = "안녕? 반가워."
    print(f"질문: {test_question}")
    answer = generate_direct_answer(test_question)
    print(f"답변:\n{answer}")