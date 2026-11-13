# Configuration settings for the encryption project

# File paths
BASE_DIR = "encryption-project/src"
KEYS_DIR = f"{BASE_DIR}/keys"
CERTS_DIR = f"{BASE_DIR}/certificates"
TEST_FILES_DIR = f"{BASE_DIR}/test_files"

# Key sizes
RSA_KEY_SIZE = 2048   # Secure minimum for AES key encryption
AES_KEY_SIZE = 32     # 256 bits

# LoRa settings
LORA_MAX_PAYLOAD = 64  # bytes per packet (matches file_transfer.py)

# File constants
ENCRYPTED_FILE_SUFFIX = ".enc"
DECRYPTED_FILE_SUFFIX = ".dec"
ENCRYPTED_FILE_PATH = f"{BASE_DIR}/encrypted_file{ENCRYPTED_FILE_SUFFIX}"
ENCRYPTED_KEY_PATH = f"{BASE_DIR}/encrypted_key.bin"
DECRYPTED_FILE_PATH = f"{BASE_DIR}/decrypted_file{DECRYPTED_FILE_SUFFIX}"


