"""
[Audit Engine] 공통 Config 로더
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
기존 step02/03/04의 개별 Config 로더(중복된 JSON 로드 로직)를 하나로 통합.
"""

import json
import os


class AuditEngineConfigLoader:
    """Audit Engine 전용 Config 로더"""

    @staticmethod
    def load_config(config_path: str) -> dict:
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config 파일을 찾을 수 없습니다: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
