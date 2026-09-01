"""
[step-4] rag-agent + audit_engine 통합 테스트 (end-to-end).

"감사 시나리오 검증"(run_audit_scenarios.py)이 audit_engine을 단독으로 검증한 것과
달리, 이 스크립트는 실제 5-api.py의 /rag, /agent 엔드포인트를 호출해 audit_hook.py가
진짜로 raw_events.json에 기록을 남기는지, 그리고 그 결과가 다시 audit_engine 파이프라인을
통과하는지까지 확인한다.

GEMINI_API_KEY 가 없는 환경에서는 LLM 호출 자체가 실패한다 — 이는 의도적으로 실패
경로(result="failure")가 감사 로그에 정상적으로 남는지 확인하는 데 쓴다. 성공 경로
(실제 답변 생성)는 이 스크립트만으로는 검증할 수 없다 — plan.md step-4에 명시.

■ 실행:
  <venv>/bin/python3 Ch03/d06/scenarios/test_api_audit_flow.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RAG_AGENT_DIR = Path(__file__).resolve().parent.parent / "rag-agent"
D06_DIR = Path(__file__).resolve().parent.parent
RAW_EVENTS_PATH = D06_DIR / "outputs" / "raw_events" / "rag_agent_events.json"


def load_api_app():
    """5-api.py 는 파일명이 숫자로 시작해 일반 import가 안 되므로 경로 로딩한다."""
    spec = importlib.util.spec_from_file_location("api_app", RAG_AGENT_DIR / "5-api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_event_count() -> int:
    if not RAW_EVENTS_PATH.exists():
        return 0
    return len(json.loads(RAW_EVENTS_PATH.read_text(encoding="utf-8")))


def main() -> None:
    from starlette.testclient import TestClient

    api = load_api_app()
    client = TestClient(api.app)

    all_passed = True

    print("=" * 78)
    print(" 1) API 기본 라우트 (Gemini 불필요)")
    print("=" * 78)
    for path in ("/health", "/documents", "/tools"):
        resp = client.get(path)
        ok = resp.status_code == 200
        all_passed = all_passed and ok
        print(f"[{'PASS' if ok else 'FAIL'}] GET {path} -> {resp.status_code}")

    print("\n" + "=" * 78)
    print(" 2) /rag, /agent 호출 -> 감사 로그 append 확인 (GEMINI_API_KEY 없는 환경)")
    print("=" * 78)

    cases = [
        ("POST /rag", lambda: client.post(
            "/rag",
            json={"question": "환불 규정이 궁금합니다", "top_k": 2},
            headers={"X-Actor": "tester_kim", "X-Role": "qa", "X-Department": "qa-team"},
        ), "rag_query"),
        ("POST /agent", lambda: client.post(
            "/agent",
            json={"question": "주말에 고객 지원 받을 수 있어?"},
            headers={"X-Actor": "tester_lee", "X-Role": "qa", "X-Department": "qa-team"},
        ), None),  # tool_name 은 실패 시 "unknown" 으로 고정되므로 사전에 알 수 없음
    ]

    for label, call, expected_action in cases:
        before = read_event_count()
        resp = call()
        after = read_event_count()

        # GEMINI_API_KEY 가 없으면 require_gemini() 가 SystemExit -> translate_error()가 500 반환.
        status_ok = resp.status_code == 500
        count_ok = after == before + 1
        passed = status_ok and count_ok
        all_passed = all_passed and passed

        print(f"[{'PASS' if passed else 'FAIL'}] {label}: status={resp.status_code}(기대 500, API 키 없음) "
              f"raw_events 개수 {before}->{after}(기대 +1)")

        if count_ok:
            last_event = json.loads(RAW_EVENTS_PATH.read_text(encoding="utf-8"))[-1]
            print(f"       기록된 이벤트: actor={last_event['actor']} action={last_event['action']} "
                  f"result={last_event['result']}")
            if last_event["result"] != "failure":
                print("       [FAIL] result 필드가 failure 로 기록되지 않음")
                all_passed = False
            if expected_action and last_event["action"] != expected_action:
                print(f"       [FAIL] action 기대값={expected_action} 실측={last_event['action']}")
                all_passed = False

    print(f"\n=> API 연동 감사 로그 테스트: {'PASS' if all_passed else 'FAIL'}")

    print("\n" + "=" * 78)
    print(" 3) 실제 API 호출로 쌓인 raw_events.json 을 audit_engine 파이프라인으로 재검증")
    print("=" * 78)
    audit_engine = sys.modules["audit_engine"]
    config_path = D06_DIR / "configs" / "audit_engine_config.json"
    config = audit_engine.AuditEngineConfigLoader.load_config(str(config_path))
    engine = audit_engine.AuditEngine(config, base_dir=str(D06_DIR))
    report = engine.inspect(str(RAW_EVENTS_PATH))
    checks = audit_engine.run_verification(report, engine.vault)
    pipeline_ok = all(c.passed for c in checks)
    all_passed = all_passed and pipeline_ok
    for check in checks:
        print(f"  [{'PASS' if check.passed else 'FAIL'}] {check.stage:<10} {check.detail}")

    print("\n" + "=" * 78)
    print(" 4) API를 거치지 않은 직접 호출도 감사가 남는지 (SDK 통일 확인)")
    print("=" * 78)
    # 5-api.py 를 전혀 거치지 않고 3-2-rag.py 의 run_rag() 를 직접 호출한다.
    # audit_hook.set_context() 를 아무도 부르지 않았으므로 AuditContext 기본값
    # (actor="anonymous", source_ip="local") 이 쓰여야 한다 — API 계층이 없어도
    # SDK(run_rag 내부)가 스스로 감사를 남긴다는 걸 보여주는 게 이 섹션의 목적이다.
    rag_direct = importlib.util.spec_from_file_location("rag_direct_test", RAG_AGENT_DIR / "3-2-rag.py")
    rag_module = importlib.util.module_from_spec(rag_direct)
    sys.modules["rag_direct_test"] = rag_module  # dataclass의 __future__ annotations 해석에 필요
    before = read_event_count()
    try:
        rag_direct.loader.exec_module(rag_module)
        rag_module.run_rag("직접 호출 테스트 질문", top_k=1)
    except BaseException:
        pass  # GEMINI_API_KEY 없는 환경에서는 실패가 정상 — 로그가 남는지만 확인
    after = read_event_count()
    direct_call_ok = after == before + 1
    if direct_call_ok:
        last_event = json.loads(RAW_EVENTS_PATH.read_text(encoding="utf-8"))[-1]
        context_ok = last_event["actor"] == "anonymous" and last_event["source_ip"] == "local"
        direct_call_ok = direct_call_ok and context_ok
        print(f"[{'PASS' if direct_call_ok else 'FAIL'}] run_rag() 직접 호출: raw_events 개수 {before}->{after}(기대 +1), "
              f"actor={last_event['actor']}(기대 anonymous) source_ip={last_event['source_ip']}(기대 local)")
    else:
        print(f"[FAIL] run_rag() 직접 호출: raw_events 개수 {before}->{after}(기대 +1) — 로그가 안 남음")
    all_passed = all_passed and direct_call_ok

    print(f"\n=> 전체 결과: {'PASS' if all_passed else 'FAIL'}")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
