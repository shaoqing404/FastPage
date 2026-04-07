import base64
import hashlib


def _derive_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def encrypt_text(secret: str, plaintext: str) -> str:
    from cryptography.fernet import Fernet

    return Fernet(_derive_key(secret)).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_text(secret: str, ciphertext: str) -> str:
    from cryptography.fernet import Fernet

    return Fernet(_derive_key(secret)).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
