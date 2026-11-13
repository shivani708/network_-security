import os
import subprocess
import zipfile
from pathlib import Path
from typing import Union,IO
from aes_utils import generate_aes_key, encrypt_data, decrypt_data
from rsa_utils import encrypt_message, decrypt_message
from config import ENCRYPTED_FILE_PATH, ENCRYPTED_KEY_PATH

class Sender:
    """
    A utility class to encrypt message using AES symmetric encryption and RSA asymmetric
    encryption for key exchange. 
    """

    def __init__(self, receiver_public_key: bytes):
        self.receiver_public_key = receiver_public_key  

    def encrypt_message(self,
                     message: bytes,
                     encypted_message: Union[str, Path] = ENCRYPTED_FILE_PATH) -> tuple[Path, bytes]:
        """
        Encrypts the message with a newly generated AES key,
        and returns the encrypted data and AES key.
        """

        aes_key = generate_aes_key()

        # Encrypt data (correct argument order)
        iv, encrypted_data = encrypt_data(message, aes_key)

        # Write iv + encrypted data to disk
        enc_data = iv + encrypted_data

        return enc_data, aes_key

    def encrypt_key(self,
                    aes_key: bytes,
                    output_path: Union[str, Path] = ENCRYPTED_KEY_PATH) -> Path:
        """
        Encrypts the AES key with the receiver's RSA public key and return the encrypted key.
        """

        # Encrypt AES key using RSA
        encrypted_key = encrypt_message(aes_key, self.receiver_public_key)

        return encrypted_key

   

class Receiver:
    def __init__(self,own_private_key: bytes):
        self.own_private_key = own_private_key

    def decrypt_key(self,
                    enc_message:bytes) -> bytes:
        """
        decrypts the AES key using the user's RSA private key. Returns the decrypted AES key as bytes.
        """
        aes_key = decrypt_message(enc_message, self.own_private_key)
        return aes_key

    def decrypt_message(self,
                     enc_message: bytes,
                     aes_key: bytes) -> bytes:
        """
        Decrypts the message using the provided `aes_key`
        and returns the plaintext .
        """

        iv = enc_message[:16]
        encrypted_data = enc_message[16:]
        plaintext = decrypt_data(iv, encrypted_data, aes_key)

        return plaintext
    


