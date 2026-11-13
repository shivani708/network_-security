# aes_utils.py
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

def generate_aes_key(key_size: int = 32) -> bytes:
    """
    Generate a random AES key.
    
    Args:
        key_size: Length of the key in bytes. Default 32 (AES-256).
    
    Returns:
        Randomly generated AES key.
    """
    return get_random_bytes(key_size)

def encrypt_data(data: bytes, key: bytes) -> tuple[bytes, bytes, bytes]:
    """
    Encrypt data using AES-GCM.
    
    Args:
        data: Plaintext bytes to encrypt.
        key: AES key bytes.
    
    Returns:
        Tuple containing (nonce, ciphertext, tag)
    """
    cipher = AES.new(key, AES.MODE_GCM)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return cipher.nonce, ciphertext, tag

def decrypt_data(nonce: bytes, ciphertext: bytes, tag: bytes, key: bytes) -> bytes:
    """
    Decrypt AES-GCM encrypted data.
    
    Args:
        nonce: Nonce used during encryption (16 bytes).
        ciphertext: Encrypted message bytes.
        tag: Authentication tag from encryption.
        key: AES key bytes.
    
    Returns:
        Decrypted plaintext bytes.
    
    Raises:
        ValueError: If authentication fails or ciphertext is tampered.
    """
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)
