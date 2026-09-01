"""
[Audit Engine] 통합 감사 로그 점검 파이프라인
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
감사 로그 파일 1개를 import하면 해시체인 무결성 검증, PII 마스킹/가명처리, 마스킹된 값의
암호화/Key Vault 저장, 보관 기간 산출 4가지 기능을 한 번에 점검하고 통합 리포트를 생성한다.

암호화 순서 원칙: 마스킹/가명처리가 항상 암호화보다 먼저 수행된다. encrypt_data에 전달되는
평문은 이벤트 원본이 아니라 마스킹(purpose)·가명처리(actor)를 거친 값이다 — 원본 PII가
그대로 암호화 입력에 들어가지 않도록 하기 위함이다.
"""

from dataclasses import asdict, dataclass
import json
import os

from .crypto import KeyVault, encrypt_data
from .hash_chain import AuditHashChain, load_entries_from_file
from .masking import mask_text, pseudonymize_actor
from .retention import AuditRetentionEngine
from .schema import AuditEvent, load_events_from_file


@dataclass(frozen=True)
class AuditLogRecord:
    """해시체인 + 마스킹/가명처리 + 암호화 + 보관정책 점검 결과를 이벤트 단위로 결합한 통합 레코드"""
    event: AuditEvent
    previous_hash: str
    entry_hash: str
    retention_days: int
    retention_until: str
    legal_basis: str
    encrypted_payload: dict
    masked_purpose: str
    pseudonymized_actor: str
    masking_findings: list[dict]


class AuditEngine:
    """감사 로그 파일 하나를 import하여 관련 기능을 한 번에 점검하는 파사드"""

    def __init__(self, config: dict, base_dir: str):
        self.config = config
        self.base_dir = base_dir

        hash_rules = config.get("hash_chain_rules", {})
        self.algorithm = hash_rules.get("hash_algorithm", "sha256")
        self.genesis_hash = hash_rules.get("genesis_previous_hash", "GENESIS")

        self.retention_engine = AuditRetentionEngine(config.get("retention_policy", {}))

        crypto_rules = config.get("crypto_rules", {})
        self.pii_fields = crypto_rules.get("target_pii_fields", ["actor", "purpose"])

        out_settings = config.get("output_settings", {})
        vault_rel_path = out_settings.get("key_vault_path", "outputs/audit_engine/key_vault.json")
        self.vault = KeyVault(os.path.join(base_dir, vault_rel_path))

    def inspect(self, log_file_path: str) -> dict:
        """
        로그 파일 1개를 import하여 해시체인/보관정책/암호화 점검을 한 번에 수행.

        파일이 이미 해시체인 결과 포맷(previous_hash/entry_hash 포함)이면 저장된 해시를
        재계산값과 대조해 실제 위변조 여부를 검증한다. raw events 포맷이면 새 체인을
        생성하며, 이 경우 체인은 방금 만들어졌으므로 항상 유효하다(검증 대상은 이후
        저장된 결과 파일을 다시 import할 때 수행됨).
        """
        existing_entries = load_entries_from_file(log_file_path)

        if existing_entries is not None:
            entries = existing_entries
            chain_valid, failed_index, failure_reason = AuditHashChain.verify_chain(
                entries, algorithm=self.algorithm, genesis_hash=self.genesis_hash
            )
        else:
            events = load_events_from_file(log_file_path)
            entries = AuditHashChain.build_chain(events, algorithm=self.algorithm, genesis_hash=self.genesis_hash)
            chain_valid, failed_index, failure_reason = True, None, None

        records = []
        for entry in entries:
            retention_info = self.retention_engine.calculate_retention(entry.event)

            # 1) 마스킹/가명처리를 먼저 수행 (암호화 입력은 이 결과값을 사용)
            masked_purpose, findings = mask_text(entry.event.purpose)
            masking_findings = [{"field": "purpose", "type": label, "value": value} for label, value in findings]
            pseudonymized_actor = pseudonymize_actor(entry.event.actor)
            deidentified_values = {"actor": pseudonymized_actor, "purpose": masked_purpose}

            # 2) 암호화는 원본이 아닌 마스킹/가명처리된 값을 대상으로 수행
            data_id = f"{entry.event.record_id}:pii"
            dek = self.vault.issue_key(data_id)
            plaintext = " | ".join(
                f"{field}:{deidentified_values.get(field, getattr(entry.event, field))}"
                for field in self.pii_fields
            )
            payload = encrypt_data(plaintext, dek)
            payload["data_id"] = data_id

            records.append(AuditLogRecord(
                event=entry.event,
                previous_hash=entry.previous_hash,
                entry_hash=entry.entry_hash,
                retention_days=retention_info["retention_days"],
                retention_until=retention_info["retention_until"],
                legal_basis=retention_info["legal_basis"],
                encrypted_payload=payload,
                masked_purpose=masked_purpose,
                pseudonymized_actor=pseudonymized_actor,
                masking_findings=masking_findings,
            ))

        self.vault.save()

        return {
            "source_file": log_file_path,
            "event_count": len(entries),
            "hash_chain": {
                "algorithm": self.algorithm,
                "valid": chain_valid,
                "failed_index": failed_index,
                "failure_reason": failure_reason,
            },
            "records": records,
        }

    @staticmethod
    def save_report(report: dict, output_path: str) -> str:
        """통합 점검 리포트를 JSON 파일로 저장"""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        serializable = {
            **{k: v for k, v in report.items() if k != "records"},
            "records": [
                {
                    "event": asdict(r.event),
                    "previous_hash": r.previous_hash,
                    "entry_hash": r.entry_hash,
                    "retention_days": r.retention_days,
                    "retention_until": r.retention_until,
                    "legal_basis": r.legal_basis,
                    "encrypted_payload": r.encrypted_payload,
                    "masked_purpose": r.masked_purpose,
                    "pseudonymized_actor": r.pseudonymized_actor,
                    "masking_findings": r.masking_findings,
                }
                for r in report["records"]
            ],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=4, ensure_ascii=False)
        return output_path
