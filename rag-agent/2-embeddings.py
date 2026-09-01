"""2-embeddings.py

문서와 질문을 Gemini 임베딩 벡터로 바꾸는 단계.
1-documents.py 의 문서를 입력으로 받고, 3-2-rag.py 에서 재사용된다.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import List

try:
    from documents import load_documents
except ModuleNotFoundError:
    # python3 2-embeddings.py 처럼 단독 실행할 때는
    # documents 라는 모듈명이 아직 등록되어 있지 않다.
    # 이 경우 1-documents.py 를 직접 읽어 load_documents 를 가져온다.
    module_path = Path(__file__).with_name("1-documents.py")
    spec = importlib.util.spec_from_file_location("documents", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["documents"] = module
    spec.loader.exec_module(module)
    load_documents = module.load_documents

# Gemini API 키는 임베딩 생성 시 필요하다.
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# 임베딩 모델 (문서/질문을 같은 공간의 벡터로 만듦)
# 2026년 기준으로 text-embedding-004 기본값은 더 이상 이 예제와 맞지 않아
# text 전용인 gemini-embedding-001을 기본값으로 사용한다.
EMBED_MODEL = os.getenv(
    "GEMINI_EMBED_MODEL",
    "models/gemini-embedding-001",
)


def _preview_embedding(vec: List[float], size: int = 8) -> str:
    """임베딩 벡터의 앞부분만 짧게 보여주기 위한 문자열."""
    preview = ", ".join(f"{value:.4f}" for value in vec[:size])
    if len(vec) > size:
        preview += ", ..."
    return f"[{preview}]"


def require_gemini():
    """google.generativeai 로드 + API 키 설정."""
    if not API_KEY:
        print(
            "GEMINI_API_KEY 가 필요합니다.\n"
            "  export GEMINI_API_KEY='your-key'",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    try:
        import google.generativeai as genai
    except ImportError:
        print(
            "패키지 필요: pip install google-generativeai",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    genai.configure(api_key=API_KEY)
    return genai


def embed_text(genai, text: str) -> List[float]:
    """문서 텍스트를 임베딩 벡터로 변환한다."""
    result = genai.embed_content(
        model=EMBED_MODEL,
        content=text,
        task_type="retrieval_document",
    )
    # SDK 버전에 따라 dict 또는 객체 형태로 응답될 수 있다.
    if isinstance(result, dict):
        vec = list(result["embedding"])
    else:
        vec = list(result.embedding)

    # 벡터는 보통 매우 길어서 전체를 다 찍기보다 앞부분만 본다.
    # 이렇게 보면 "숫자 배열이 실제로 만들어졌는지"와 "차원 수가 몇 개인지"
    # 빠르게 확인할 수 있다.
    print(
        f"    embedding dim={len(vec)} preview={_preview_embedding(vec)}",
        flush=True,
    )
    return vec


def embed_query(genai, text: str) -> List[float]:
    """질문 텍스트를 검색용 임베딩 벡터로 변환한다."""
    result = genai.embed_content(
        model=EMBED_MODEL,
        content=text,
        task_type="retrieval_query",
    )
    if isinstance(result, dict):
        vec = list(result["embedding"])
    else:
        vec = list(result.embedding)

    # 질문 임베딩도 같은 방식으로 출력해두면
    # 검색 시 문서 벡터와 같은 차원으로 만들어졌는지 확인하기 쉽다.
    print(
        f"  query embedding dim={len(vec)} preview={_preview_embedding(vec)}",
        flush=True,
    )
    return vec


def main() -> None:
    """학습용 출력: 문서 임베딩과 질문 임베딩을 직접 보여준다."""
    print("=" * 60, flush=True)
    print("2-embeddings.py 데모", flush=True)
    print("=" * 60, flush=True)

    documents = load_documents()
    sample_doc = documents[0]
    sample_query = "서울 여름 날씨는 어때?"

    print("[1] 샘플 문서", flush=True)
    print(
        f"  - Document(doc_id={sample_doc.doc_id!r}, text={sample_doc.text!r})",
        flush=True,
    )

    print("[2] Gemini 임베딩 준비", flush=True)
    genai = require_gemini()
    print(f"  - embed model: {EMBED_MODEL}", flush=True)

    print("[3] 문서 임베딩", flush=True)
    embed_text(genai, sample_doc.text)

    print("[4] 질문 임베딩", flush=True)
    print(f"  - query: {sample_query}", flush=True)
    embed_query(genai, sample_query)


if __name__ == "__main__":
    main()
