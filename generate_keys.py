# key_generation.py
from pathlib import Path
from rsa_utils import generate_private_key, generate_public_key
from config import KEYS_DIR, RSA_KEY_SIZE

# Ensure keys directory exists
Path(KEYS_DIR).mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    priv_path = Path(KEYS_DIR) / "receiver_private.pem"
    pub_path = Path(KEYS_DIR) / "receiver_public.pem"

    # Generate RSA private key
    generate_private_key(priv_path, key_size=RSA_KEY_SIZE)
    
    # Extract public key from private key
    generate_public_key(priv_path, pub_path)

    print("✅ Keys generated successfully:")
    print(f" - Private key (keep safe on Receiver/Base only): {priv_path}")
    print(f" - Public key (copy to Sender/Drone): {pub_path}")
