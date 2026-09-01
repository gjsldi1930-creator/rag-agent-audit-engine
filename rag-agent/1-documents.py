# 1-documents.py
# =============================================================================
# RAG 예제의 문서 모델과 문서 로더
#
# 역할:
#   1) Document 데이터 구조를 정의한다.
#   2) 1-documents.json 파일을 읽어 Document 목록으로 바꾼다.
#
# 3-2-rag.py 에서:
#   from documents import Document, load_documents
# =============================================================================

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

# 샘플 문서는 코드 밖의 JSON 파일에 둔다.
# 이렇게 해두면 문서 내용을 바꿀 때 파이썬 코드를 수정하지 않아도 된다.
# 이 예제는 단계 번호가 붙은 파일명을 기본으로 사용한다.
DOCUMENTS_PATH = Path(__file__).with_name("documents.txt")
if not DOCUMENTS_PATH.exists():
    DOCUMENTS_PATH = Path(__file__).with_name("1-documents.json")


@dataclass
class Document:
    """RAG 에 넣을 한 덩어리 문서.

    doc_id : 식별자
    text   : 실제 내용 (나중에 프롬프트 Context 로 들어감)
    """

    doc_id: str
    text: str


def load_documents() -> List[Document]:
    """JSON 파일에서 문서를 읽어 Document 목록으로 변환한다.

    기대하는 JSON 형식:
    [
      {"doc_id": "weather", "text": "..."},
      {"doc_id": "product", "text": "..."}
    ]
    """
    # JSON 파일을 문자열로 읽고, 파이썬 리스트/딕셔너리 구조로 변환한다.
    rows = json.loads(DOCUMENTS_PATH.read_text(encoding="utf-8"))

    # 각 JSON 항목을 Document 객체로 바꿔서 3-2-rag.py 가 바로 사용할 수 있게 만든다.
    return [Document(doc_id=row["doc_id"], text=row["text"]) for row in rows]


def main() -> None:
    """학습용 출력: JSON 원본과 변환된 Document 목록을 보여준다."""
    print("=" * 60, flush=True)
    print("1-documents.py 데모", flush=True)
    print("=" * 60, flush=True)

    print("[1] JSON 파일 위치", flush=True)
    print(f"  {DOCUMENTS_PATH}", flush=True)

    print("[2] JSON 원본", flush=True)
    rows = json.loads(DOCUMENTS_PATH.read_text(encoding="utf-8"))
    for row in rows:
        print(f"  - {row}", flush=True)

    print("[3] Document 객체로 변환된 결과", flush=True)
    for doc in load_documents():
        print(f"  - Document(doc_id={doc.doc_id!r}, text={doc.text!r})", flush=True)


if __name__ == "__main__":
    main()
