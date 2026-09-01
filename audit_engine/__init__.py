"""
Audit Engine
~~~~~~~~~~~~
해시체인(hash_chain) + 보관정책(retention) + 암호화/Key Vault(crypto) 3가지 기능을 통합한
감사 로그 점검 엔진. 기존 lab10_step0*.py 소스에 의존하지 않는 독립 패키지이며,
로그 파일 1개를 import하면 AuditEngine.inspect()로 3가지 기능을 한 번에 점검한다.
"""

from .config import AuditEngineConfigLoader
from .crypto import KeyNotFoundError, KeyVault, decrypt_data, encrypt_data, keystream
from .engine import AuditEngine, AuditLogRecord
from .hash_chain import AuditHashChain, AuditLogEntry, load_entries_from_file
from .masking import anonymize_department, mask_text, pseudonymize_actor
from .retention import AuditRetentionEngine
from .schema import AuditEvent, load_events_from_file
from .verify import CheckResult, check_encryption, check_hash_chain, check_masking, check_retention, run_verification

__all__ = [
    "AuditEngineConfigLoader",
    "KeyNotFoundError",
    "KeyVault",
    "decrypt_data",
    "encrypt_data",
    "keystream",
    "AuditEngine",
    "AuditLogRecord",
    "AuditHashChain",
    "AuditLogEntry",
    "load_entries_from_file",
    "anonymize_department",
    "mask_text",
    "pseudonymize_actor",
    "AuditRetentionEngine",
    "AuditEvent",
    "load_events_from_file",
    "CheckResult",
    "check_encryption",
    "check_hash_chain",
    "check_masking",
    "check_retention",
    "run_verification",
]
