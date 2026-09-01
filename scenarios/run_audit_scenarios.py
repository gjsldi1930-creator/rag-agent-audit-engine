"""
[d06] RAG 에이전트 감사 시나리오 검증 러너
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
rag_audit_events.json 에 정의된 8개 시나리오(마스킹 4종, 실패 결과, 정책 미매핑/
매핑 대조)를 audit-engine 파이프라인에 통과시키고, 기대값과 실측값을 대조한다.
이어서 해시체인 결과 파일을 조작해 위변조 탐지 여부까지 확인한다.

audit-engine 디렉터리명이 하이픈이라 `python -m audit_engine` / 일반 import 모두
불가능하므로, rag-agent 쪽 모듈 로딩과 동일하게 importlib 경로 로딩을 사용한다.

■ 실행:
  python3 Ch03/d06/scenarios/run_audit_scenarios.py
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

D06_DIR = Path(__file__).resolve().parent.parent
SCENARIO_FILE = Path(__file__).resolve().parent / "rag_audit_events.json"
CONFIG_FILE = D06_DIR / "configs" / "audit_engine_config.json"
TAMPERED_CHAIN_FILE = Path(__file__).resolve().parent / "tampered_chain.json"


def load_audit_engine():
    """audit-engine(하이픈) 디렉터리를 모듈명 audit_engine 으로 경로 로드한다."""
    package_dir = D06_DIR / "audit-engine"
    spec = importlib.util.spec_from_file_location(
        "audit_engine",
        package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"audit-engine 을 로드할 수 없습니다: {package_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_engine"] = module
    spec.loader.exec_module(module)
    return module


AE = load_audit_engine()

# 시나리오별 기대값: (record_id -> 검증 항목)
EXPECTATIONS = {
    "rag-001": {"masking_types": set(), "retention_days": 365, "note": "베이스라인 (PII 없음)"},
    "rag-002": {"masking_types": {"email"}, "retention_days": 365, "note": "이메일 마스킹 탐지"},
    "rag-003": {"masking_types": {"phone"}, "retention_days": 365, "note": "전화번호 마스킹 탐지"},
    "rag-004": {"masking_types": {"name"}, "retention_days": 365, "note": "문맥 기반 이름 마스킹 탐지"},
    "rag-005": {"masking_types": {"card"}, "retention_days": 365, "note": "카드번호 마스킹 탐지"},
    "rag-006": {"masking_types": set(), "retention_days": 365, "note": "실패 결과 + action 미매핑 default 폴백"},
    "rag-007": {"masking_types": set(), "retention_days": 730, "note": "기존 enterprise 정책(export_pii) 매핑 대조"},
    "rag-008": {"masking_types": set(), "retention_days": 365, "note": "step-3 신규 action(direct_llm_response) 폴백"},
}


def run_scenarios() -> dict:
    config = AE.AuditEngineConfigLoader.load_config(str(CONFIG_FILE))
    engine = AE.AuditEngine(config, base_dir=str(D06_DIR))
    report = engine.inspect(str(SCENARIO_FILE))

    print("=" * 78)
    print(" 1) 정상 시나리오 실행 결과")
    print("=" * 78)

    all_passed = True
    for record in report["records"]:
        expected = EXPECTATIONS[record.event.record_id]
        actual_types = {f["type"] for f in record.masking_findings}
        masking_ok = actual_types == expected["masking_types"]
        retention_ok = record.retention_days == expected["retention_days"]
        passed = masking_ok and retention_ok
        all_passed = all_passed and passed

        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {record.event.record_id:<8} action={record.event.action:<20} "
              f"result={record.event.result:<8} | {expected['note']}")
        print(f"       마스킹 탐지: 기대={sorted(expected['masking_types']) or '없음'} "
              f"실측={sorted(actual_types) or '없음'}")
        print(f"       보관기간: 기대={expected['retention_days']}일 실측={record.retention_days}일 "
              f"(법적근거: {record.legal_basis})")
        if record.masking_findings:
            print(f"       원본 purpose : {record.event.purpose}")
            print(f"       마스킹 결과  : {record.masked_purpose}")

    chain = report["hash_chain"]
    print(f"\n해시체인({chain['algorithm']}) 무결성: {'정상' if chain['valid'] else '위변조 감지'}")

    checks = AE.run_verification(report, engine.vault)
    print("\n파이프라인 단계별 재검증:")
    for check in checks:
        print(f"  [{'PASS' if check.passed else 'FAIL'}] {check.stage:<10} {check.detail}")
        all_passed = all_passed and check.passed

    report_dir = D06_DIR / "outputs" / "audit_engine"
    report_path = report_dir / "scenario_report.json"
    AE.AuditEngine.save_report(report, str(report_path))
    print(f"\n리포트 저장: {report_path}")

    print(f"\n=> 전체 시나리오 결과: {'PASS' if all_passed else 'FAIL'}")
    return report


def run_tamper_test(report: dict) -> None:
    """해시체인 결과 파일을 조작해 verify_chain 이 위변조를 실제로 잡아내는지 확인."""
    print("\n" + "=" * 78)
    print(" 2) 위변조 탐지 시나리오")
    print("=" * 78)

    # save_report() 산출물은 {source_file, event_count, hash_chain, records:[...]} 형태의
    # dict라서 load_entries_from_file() 이 요구하는 최상위 list 형식이 아니다.
    # records 배열만 뽑아 별도 list 파일로 저장해야 재검증(inspect) 대상이 될 수 있다.
    from dataclasses import asdict
    entries = [
        {
            "event": asdict(r.event),
            "previous_hash": r.previous_hash,
            "entry_hash": r.entry_hash,
        }
        for r in report["records"]
    ]

    tampered = copy.deepcopy(entries)
    target = tampered[2]  # rag-003
    original_purpose = target["event"]["purpose"]
    target["event"]["purpose"] = "조작된 목적 텍스트로 사후 변경됨"
    # entry_hash 는 그대로 둔 채(=위변조 상황 재현) event 내용만 바꾼다.

    TAMPERED_CHAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TAMPERED_CHAIN_FILE, "w", encoding="utf-8") as f:
        json.dump(tampered, f, ensure_ascii=False, indent=2)

    config = AE.AuditEngineConfigLoader.load_config(str(CONFIG_FILE))
    engine = AE.AuditEngine(config, base_dir=str(D06_DIR))
    tampered_report = engine.inspect(str(TAMPERED_CHAIN_FILE))
    chain = tampered_report["hash_chain"]

    detected = not chain["valid"] and chain["failed_index"] == 3 and chain["failure_reason"] == "tampered"
    print(f"[{'PASS' if detected else 'FAIL'}] entry #3 purpose 변조: "
          f"'{original_purpose}' -> '{target['event']['purpose']}'")
    print(f"       탐지 결과: valid={chain['valid']} failed_index={chain['failed_index']} "
          f"reason={chain['failure_reason']}")
    print(f"\n=> 위변조 탐지 시나리오: {'PASS' if detected else 'FAIL'}")


if __name__ == "__main__":
    report = run_scenarios()
    run_tamper_test(report)
