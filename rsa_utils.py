# rsa_utils.py
import os
from pathlib import Path
from typing import Union
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Signature import pss
from Crypto.Hash import SHA256


# ==========================
# RSA Key Generation
# ==========================
def generate_private_key(path: Union[str, Path] = "receiver_private.pem", key_size: int = 2048):
    """
    Generate an RSA private key and save it to a file.
    Default key size = 2048 bits (recommended).
    """
    key = RSA.generate(key_size)
    with open(path, "wb") as f:
        f.write(key.export_key("PEM"))
    return path


def generate_public_key(private_path: Union[str, Path], public_path: Union[str, Path] = "receiver_public.pem"):
    """
    Extract the public key from a private key file and save it separately.
    """
    with open(private_path, "rb") as f:
        priv_key = RSA.import_key(f.read())
    pub_key = priv_key.publickey()
    with open(public_path, "wb") as f:
        f.write(pub_key.export_key("PEM"))
    return public_path


# ==========================
# RSA Encryption / Decryption
# ==========================
def encrypt_message(message: Union[str, bytes], public_key: bytes) -> bytes:
    """
    Encrypt a small message (e.g., AES key) using RSA public key.
    Uses PKCS1_OAEP padding (secure).
    """
    if isinstance(message, str):
        message = message.encode()

    pub_key = RSA.import_key(public_key)
    cipher = PKCS1_OAEP.new(pub_key)
    return cipher.encrypt(message)


def decrypt_message(encrypted_message: bytes, private_key: bytes) -> bytes:
    """
    Decrypt a message using RSA private key.
    Returns raw bytes (caller can decode if needed).
    """
    priv_key = RSA.import_key(private_key)
    cipher = PKCS1_OAEP.new(priv_key)
    try:
        return cipher.decrypt(encrypted_message)
    except ValueError:
        print("❌ RSA decryption failed – wrong key or corrupted ciphertext.")
        return "BER"
        raise ValueError("❌ RSA decryption failed – wrong key or corrupted ciphertext.")


# ==========================
# Optional Signing / Verify
# ==========================
def sign_message(message: bytes, private_key: bytes) -> bytes:
    """Sign a message with RSA-PSS."""
    priv_key = RSA.import_key(private_key)
    h = SHA256.new(message)
    return pss.new(priv_key).sign(h)


def verify_signature(message: bytes, signature: bytes, public_key: bytes) -> bool:
    """Verify RSA-PSS signature."""
    pub_key = RSA.import_key(public_key)
    h = SHA256.new(message)
    try:
        pss.new(pub_key).verify(h, signature)
        return True
    except (ValueError, TypeError):
        return False


# ==========================
# Helpers
# ==========================
def load_key(path: Union[str, Path]) -> bytes:
    """Load a PEM key file into memory."""
    with open(path, "rb") as f:
        return f.read()
