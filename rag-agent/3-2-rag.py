# 3-2-rag.py
# =============================================================================
# RAG (Retrieval-Augmented Generation) 설명용 샘플
#
# 데이터 흐름 (한 줄):
#   Document → Embed → Vector DB → search → Prompt → LLM → 답변
#
# 각 단계:
#   1) Document   : 참고할 텍스트(지식)를 준비한다
#   2) Embed      : 텍스트를 숫자 벡터로 바꾼다 (의미 유사도 비교용)
#   3) Vector DB  : 벡터를 저장한다 (여기선 메모리 리스트로 단순화)
#   4) search     : 질문 벡터와 가장 비슷한 문서를 찾는다
#   5) Prompt     : 찾은 문서(Context) + 질문을 프롬프트로 합친다
#   6) LLM        : 3-1-llm.py 가 Gemini 를 호출해 답변을 생성한다
#
# 예제 모듈:
#   1-documents.py (Document, load_documents)
#   2-embeddings.py (embed_text, embed_query)
#   3-1-llm.py      (require_gemini, generate_answer)
#
# 실행:
#   python3 3-2-rag.py
# =============================================================================

from __future__ import annotations

import importlib.util
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
import audit_hook  # noqa: E402

try:
    from documents import Document, load_documents
except ModuleNotFoundError:
    module_path = Path(__file__).with_name("1-documents.py")
    spec = importlib.util.spec_from_file_location("documents", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["documents"] = module
    spec.loader.exec_module(module)
    Document = module.Document
    load_documents = module.load_documents

try:
    from embeddings import embed_query, embed_text
except ModuleNotFoundError:
    module_path = Path(__file__).with_name("2-embeddings.py")
    spec = importlib.util.spec_from_file_location("embeddings", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["embeddings"] = module
    spec.loader.exec_module(module)
    embed_query = module.embed_query
    embed_text = module.embed_text

try:
    from llm import generate_answer, require_gemini
except ModuleNotFoundError:
    module_path = Path(__file__).with_name("3-1-llm.py")
    spec = importlib.util.spec_from_file_location("llm", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["llm"] = module
    spec.loader.exec_module(module)
    generate_answer = module.generate_answer
    require_gemini = module.require_gemini


@dataclass
class VectorRecord:
    """벡터 DB 한 행: 문서 + 그 문서의 임베딩."""

    document: Document
    embedding: List[float]


class InMemoryVectorDB:
    """실제 Chroma/Pinecone 대신 리스트로 저장."""

    def __init__(self) -> None:
        self._rows: List[VectorRecord] = []

    def add(self, document: Document, embedding: Sequence[float]) -> None:
        self._rows.append(
            VectorRecord(document=document, embedding=list(embedding))
        )

    def all(self) -> List[VectorRecord]:
        return list(self._rows)


def build_index(genai, documents: List[Document]) -> InMemoryVectorDB:
    """문서를 임베딩해 메모리 벡터 DB 에 적재한다."""
    db = InMemoryVectorDB()
    print("[1–3] Document → Embed → Vector DB", flush=True)
    for doc in documents:
        print(f"  - embedding document {doc.doc_id!r}", flush=True)
        vec = embed_text(genai, doc.text)
        db.add(doc, vec)
        print(f"  + indexed {doc.doc_id!r} (dim={len(vec)})", flush=True)
    return db


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """코사인 유사도: 1에 가까울수록 방향이 비슷."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def search(
    genai,
    db: InMemoryVectorDB,
    query: str,
    top_k: int = 2,
) -> List[Tuple[Document, float]]:
    """질문 임베딩 후 DB 에서 유사도 상위 top_k 문서 반환."""
    print(f"[4] search query={query!r} top_k={top_k}", flush=True)
    q_vec = embed_query(genai, query)
    scored: List[Tuple[Document, float]] = []
    for row in db.all():
        score = cosine_similarity(q_vec, row.embedding)
        scored.append((row.document, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    hits = scored[:top_k]
    for doc, score in hits:
        print(f"  hit {doc.doc_id!r} score={score:.4f}", flush=True)
    return hits

# roe
def build_prompt(question: str, contexts: List[Document]) -> str:
    """검색된 문서를 Context 로 붙인 사용자 프롬프트 작성."""
    if not contexts:
        context_block = "(관련 문서 없음)"
    else:
        parts = [f"[{c.doc_id}] {c.text}" for c in contexts]
        context_block = "\n".join(parts)

    prompt = f"""다음 Context 만 근거로 질문에 답하세요.
Context 에 없는 내용은 추측하지 말고 '문서에 없습니다'라고 하세요.

--- Context ---
{context_block}
---

Question: {question}
"""
    print("[5] Prompt 조립 (Context + Question)", flush=True)
    return prompt


def run_rag(question: str, top_k: int = 2) -> str:
    """Document → Embed → Vector DB → search → Prompt → LLM → 답변

    이 함수가 호출 결과를 스스로 감사 로그에 남긴다(action="rag_query") — /rag 엔드포인트가
    직접 부르든, 에이전트가 tool_rag를 통해 부르든, CLI(main())로 직접 실행하든 동일하게
    기록된다. actor/source_ip 등은 audit_hook.set_context()로 미리 심어둔 값을 쓴다.
    """
    try:
        documents = load_documents()
        print("[1] Document 로드", flush=True)
        for doc in documents:
            print(f"  - document {doc.doc_id!r}: {doc.text}", flush=True)

        genai = require_gemini()
        db = build_index(genai, documents)
        hits = search(genai, db, question, top_k=top_k)
        contexts = [doc for doc, _score in hits]
        prompt = build_prompt(question, contexts)
        answer = generate_answer(genai, prompt)
    except BaseException:
        audit_hook.log_event(action="rag_query", purpose=question, result="failure")
        raise
    audit_hook.log_event(action="rag_query", purpose=question, result="success")
    return answer


def main() -> None:
    print("=" * 60)
    print("RAG 데모 (Gemini)")
    print("Document → Embed → Vector DB → search → Prompt → LLM")
    print("=" * 60)

    questions = [
        "서울 여름 날씨는 어때?",
        "주말에 고객 지원 받을 수 있어?",
        "비행기 표 환불 규정 알려줘",
    ]

    for i, q in enumerate(questions, 1):
        print()
        print(f"======== 질문 {i}: {q} ========")
        try:
            answer = run_rag(q, top_k=2)
        except Exception as exc:
            print(f"[오류] {exc}", file=sys.stderr)
            sys.exit(1)
        print("--- 답변 ---")
        print(answer)
        print()


if __name__ == "__main__":
    main()
