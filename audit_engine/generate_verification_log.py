"""
[Audit Engine] 파이프라인 검증용 로그 생성 스크립트
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
lab10_step01_schema_generator.py(원본 5W1H 감사 데이터 생성기)를 이용해 audit_engine
파이프라인 검증용 감사 로그를 생성하고 src/audit_engine/fixtures/에 저장한다.

주의: 이 스크립트는 "검증용 테스트 데이터 생성" 목적으로만 step01을 사용한다.
audit_engine 패키지 본체(schema/engine/hash_chain/retention/crypto)는 여전히
lab10_step0*.py를 import하지 않는 독립 구현이며, 이 스크립트만 예외적으로
step01을 가져와 데이터를 만든다.

■ 사용 방법:
  $ cd Ch03/d05/src
  $ python3 audit_engine/generate_verification_log.py
"""

from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab10_step01_schema_generator import AuditDummyGenerator  # noqa: E402


def generate_verification_log() -> str:
    src_dir = Path(__file__).resolve().parent.parent
    base_dir = src_dir.parent
    generator_config_path = base_dir / "configs" / "lab10_generator_config.json"

    generator = AuditDummyGenerator()
    events, _ = generator.generate_from_config(str(generator_config_path))

    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    fixtures_dir.mkdir(exist_ok=True)

    time_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = fixtures_dir / f"verification_log_{time_suffix}.json"
    generator.save_to_json(events, str(output_path))

    return str(output_path)


def main():
    print("=" * 80)
    print(" [Audit Engine] 파이프라인 검증용 로그 생성")
    print("=" * 80)

    output_path = generate_verification_log()

    print(f"💾 검증용 감사 로그 저장 완료: {output_path}")
    print("\n👉 파이프라인 검증 실행 예시: (src/ 디렉터리에서 실행)")
    print(f"   python -m audit_engine audit_engine/fixtures/{Path(output_path).name}")


if __name__ == "__main__":
    main()
