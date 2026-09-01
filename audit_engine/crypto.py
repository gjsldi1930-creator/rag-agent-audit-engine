"""
[Audit Engine] 스트림 암호화 및 Key Vault(DEK 저장소) 관리
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
민감 필드를 DEK(Data Encryption Key)로 스트림 암호화하고, DEK는 별도 Key Vault 파일에 저장한다.
Key Vault에서 DEK를 삭제(shred_key)하면 해당 데이터는 영구히 복호화 불가능해진다 (Crypto-Shredding).
기존 step04a/04b에 중복 정의되어 있던 keystream 함수를 하나로 통합한 독립 재구현.
"""

import base64
import hashlib
import json
import os
import secrets


class KeyNotFoundError(Exception):
    """키가 삭제(Crypto-Shredded)되었거나 Key Vault에 존재하지 않을 때 발생하는 예외"""
    pass


def keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        counter_bytes = counter.to_bytes(4, byteorder="big")
        block = hashlib.sha256(key + nonce + counter_bytes).digest()
        output.extend(block)
        counter += 1
    return bytes(output[:length])


def encrypt_data(plaintext: str, key: bytes) -> dict:
    """민감 데이터를 DEK 키로 스트림 암호화"""
    nonce = secrets.token_bytes(16)
    raw_bytes = plaintext.encode("utf-8")
    ks = keystream(key, nonce, len(raw_bytes))
    ciphertext = bytes(a ^ b for a, b in zip(raw_bytes, ks))
    return {
        "nonce_b64": base64.b64encode(nonce).decode("utf-8"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("utf-8"),
    }


def decrypt_data(payload: dict, key: bytes) -> str:
    """DEK 키로 암호문 복호화"""
    nonce = base64.b64decode(payload["nonce_b64"])
    ciphertext = base64.b64decode(payload["ciphertext_b64"])
    ks = keystream(key, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, ks)).decode("utf-8")


class KeyVault:
    """DEK(Data Encryption Key) 저장소 파일 입출력 및 Crypto-Shredding 관리"""

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self._vault = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.vault_path):
            with open(self.vault_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def issue_key(self, data_id: str) -> bytes:
        """새 DEK를 발급해 Vault에 등록"""
        dek = secrets.token_bytes(32)
        self._vault[data_id] = base64.b64encode(dek).decode("utf-8")
        return dek

    def get_key(self, data_id: str) -> bytes:
        if data_id not in self._vault:
            raise KeyNotFoundError(f"[Crypto-Shredded] 데이터 키 '{data_id}'가 Key Vault에서 삭제되어 복호화 불가능합니다.")
        return base64.b64decode(self._vault[data_id])

    def shred_key(self, data_id: str) -> None:
        """데이터 키 영구 삭제 (Crypto-Shredding)"""
        self._vault.pop(data_id, None)

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.vault_path)), exist_ok=True)
        with open(self.vault_path, "w", encoding="utf-8") as f:
            json.dump(self._vault, f, indent=4, ensure_ascii=False)
