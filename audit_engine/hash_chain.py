"""
[Audit Engine] 체인형 해시 결합 및 위변조 탐지 엔진
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
이전 로그 해시(previous_hash)와 현재 이벤트를 연쇄 결합해 체인을 형성하고,
중간 로그가 변경되면 해시 검증이 실패해 위변조를 탐지한다 (기존 step02와 동일 알고리즘, 독립 재구현).
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import os

from .schema import AuditEvent


@dataclass(frozen=True)
class AuditLogEntry:
    event: AuditEvent
    previous_hash: str
    entry_hash: str


class AuditHashChain:
    """체인형 해시 생성, 파일 저장 및 무결성 검증 엔진"""

    @staticmethod
    def canonical_json(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def compute_hash(cls, event: AuditEvent, previous_hash: str, algorithm: str = "sha256") -> str:
        """설정된 해시 알고리즘(sha256, sha512, sha3_256 등)에 따라 동적 해시 생성"""
        payload = {
            "event": asdict(event),
            "previous_hash": previous_hash,
        }
        encoded_data = cls.canonical_json(payload).encode("utf-8")

        algo_name = algorithm.lower().replace("-", "")
        if algo_name == "sha512":
            return hashlib.sha512(encoded_data).hexdigest()
        elif algo_name == "sha3_256":
            return hashlib.sha3_256(encoded_data).hexdigest()
        else:
            return hashlib.sha256(encoded_data).hexdigest()

    @classmethod
    def build_chain(cls, events: list[AuditEvent], algorithm: str = "sha256", genesis_hash: str = "GENESIS") -> list[AuditLogEntry]:
        entries = []
        previous_hash = genesis_hash

        for event in events:
            entry_hash = cls.compute_hash(event, previous_hash, algorithm)
            entries.append(AuditLogEntry(event=event, previous_hash=previous_hash, entry_hash=entry_hash))
            previous_hash = entry_hash

        return entries

    @classmethod
    def verify_chain(cls, entries: list[AuditLogEntry], algorithm: str = "sha256", genesis_hash: str = "GENESIS") -> tuple[bool, int | None, str | None]:
        """체인 무결성을 검증하고 (정상 여부, 실패 엔트리 번호, 실패 사유)를 반환"""
        expected_previous = genesis_hash

        for idx, entry in enumerate(entries, start=1):
            if entry.previous_hash != expected_previous:
                return False, idx, "broken_link"

            expected_hash = cls.compute_hash(entry.event, entry.previous_hash, algorithm)
            if entry.entry_hash != expected_hash:
                return False, idx, "tampered"

            expected_previous = entry.entry_hash

        return True, None, None

    @classmethod
    def save_chain_to_json(cls, entries: list[AuditLogEntry], output_path: str) -> str:
        """해시체인이 결합된 AuditLogEntry 리스트를 JSON 파일로 저장"""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        serialized_entries = [
            {
                "event": asdict(entry.event),
                "previous_hash": entry.previous_hash,
                "entry_hash": entry.entry_hash,
            }
            for entry in entries
        ]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(serialized_entries, f, indent=4, ensure_ascii=False)
        return output_path


def load_entries_from_file(filepath: str) -> list[AuditLogEntry] | None:
    """
    파일이 이미 해시체인 결과 포맷(event/previous_hash/entry_hash)이면 저장된 해시값을
    그대로 보존해 AuditLogEntry 리스트로 로드한다. raw events 포맷이면 None을 반환한다.

    이렇게 저장된 해시를 보존해야만 verify_chain으로 위변조(저장된 해시 대비 재계산 불일치)를
    실제로 탐지할 수 있다. raw events로부터 매번 새로 체인을 만들면 항상 자기 자신과
    일치하므로 검증이 무의미해진다.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"로그 파일을 찾을 수 없습니다: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    if not isinstance(raw_json, list) or not raw_json:
        return None

    first_item = raw_json[0]
    if not isinstance(first_item, dict) or not {"event", "previous_hash", "entry_hash"} <= first_item.keys():
        return None

    return [
        AuditLogEntry(
            event=AuditEvent(**item["event"]),
            previous_hash=item["previous_hash"],
            entry_hash=item["entry_hash"],
        )
        for item in raw_json
    ]
