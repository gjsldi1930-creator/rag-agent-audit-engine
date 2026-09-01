"""
[Audit Engine] 통합 감사 로그 점검 CLI
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
■ 사용 방법:
  $ cd Ch03/d05/src
  $ python -m audit_engine <log_file_path> [--config <config_path>]

  <log_file_path> : 점검할 감사 로그 JSON 파일 (raw events 또는 hash-chain 결과 파일 모두 지원)
  --config        : 사용할 config 파일 경로 (기본값: configs/audit_engine_config.json)
"""

import argparse
from dataclasses import asdict
from datetime import datetime
import os
from pathlib import Path

from .config import AuditEngineConfigLoader
from .engine import AuditEngine
from .verify import run_verification


def main():
    parser = argparse.ArgumentParser(description="감사 로그 통합 점검 파이프라인 (해시체인/보관정책/암호화)")
    parser.add_argument("log_file", help="점검할 감사 로그 JSON 파일 경로")
    parser.add_argument("--config", default=None, help="Audit Engine config 파일 경로")
    args = parser.parse_args()

    # d06/audit-engine 은 원본(d05/src/audit_engine)과 달리 src/ 중간 계층이 없는
    # 평탄화된 구조이므로 base_dir 은 audit-engine 의 부모(d06) 한 단계만 올라간다.
    base_dir = Path(__file__).resolve().parent.parent
    config_path = args.config or str(base_dir / "configs" / "audit_engine_config.json")

    print("=" * 80)
    print(" [Audit Engine] 통합 감사 로그 점검 파이프라인")
    print("=" * 80)

    try:
        config = AuditEngineConfigLoader.load_config(config_path)
        print(f"⚙️ Config 로드 성공: {config_path}")
    except Exception as e:
        print(f"❌ Config 로드 실패: {str(e)}")
        return

    log_path = args.log_file
    if not os.path.isabs(log_path) and not os.path.exists(log_path):
        candidate = base_dir / log_path
        if candidate.exists():
            log_path = str(candidate)

    engine = AuditEngine(config, str(base_dir))

    try:
        report = engine.inspect(log_path)
    except Exception as e:
        print(f"❌ 로그 파일 점검 실패: {str(e)}")
        return

    chain = report["hash_chain"]
    print(f"📂 점검 대상 로그 파일: {report['source_file']}")
    print(f"📋 총 이벤트 수: {report['event_count']}개")
    if chain["valid"]:
        print(f"🔗 해시체인({chain['algorithm'].upper()}) 무결성: ✅ 정상\n")
    else:
        print(f"🔗 해시체인({chain['algorithm'].upper()}) 무결성: 🚨 위변조 감지 "
              f"(엔트리 #{chain['failed_index']}, 사유: {chain['failure_reason']})\n")

    for idx, r in enumerate(report["records"], start=1):
        mask_summary = f"🚨탐지 {len(r.masking_findings)}건" if r.masking_findings else "탐지없음"
        print(f"[{idx}] Action:{r.event.action:<20} | 보관기간:{r.retention_days}일(~{r.retention_until}) | "
              f"근거:{r.legal_basis} | PII암호화:✅({r.encrypted_payload['data_id']}) | 마스킹:{mask_summary}")
        if r.masking_findings:
            types = ", ".join(sorted({finding["type"] for finding in r.masking_findings}))
            print(f"      원본 purpose : {r.event.purpose}")
            print(f"      마스킹 결과  : {r.masked_purpose}")
            print(f"      탐지 유형    : {types}")

    checks = run_verification(report, engine.vault)
    print("\n🔍 [파이프라인 단계별 중간 검증]")
    for check in checks:
        status = "✅" if check.passed else "❌"
        print(f"  {status} {check.stage:<10} | {check.detail}")
    report["verification"] = [asdict(check) for check in checks]

    time_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_settings = config.get("output_settings", {})
    report_dir = base_dir / out_settings.get("report_dir", "outputs/audit_engine")
    report_path = report_dir / f"audit_engine_report_{time_suffix}.json"
    saved = AuditEngine.save_report(report, str(report_path))

    print(f"\n💾 [통합 점검 리포트 저장 완료]")
    print(f"   • 저장 경로: {saved}")
    print("\n✅ Audit Engine 통합 점검 완료.")


if __name__ == "__main__":
    main()
