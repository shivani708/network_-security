import os
import threading
import lora_transceiver
import lora
from aes_utils import decrypt_data
from file_transfer import Receiver
from Crypto.PublicKey import RSA
import json
# MAVLink parsing
from pymavlink import mavutil

# Silence UHD spam logs
os.environ.setdefault("UHD_LOG_LEVEL", "error")

# --- Headers ---
HEADER_KEY = 0xA1     # Initial AES session key
HEADER_DATA = 0xB1    # Encrypted MAVLink data

# --- AES Key Storage ---
AES_KEY_FILE = "aes_key.json"


def save_aes_key(aes_key: bytes):
    with open(AES_KEY_FILE, "w") as f:
        json.dump({"key": aes_key.hex()}, f)


def load_aes_key():
    if os.path.exists(AES_KEY_FILE):
        with open(AES_KEY_FILE, "r") as f:
            return bytes.fromhex(json.load(f)["key"])
    return None


# --- State ---
enc_key_bytes = bytearray()
aes_key = None
got_key = False
rsa_modulus_len = None  # detected from key


def main():
    """
    Secure LoRa receiver for MAVLink:
    - Reassembles RSA-encrypted AES key
    - Then decrypts MAVLink messages with AES-GCM
    """
    global enc_key_bytes, got_key, aes_key, rsa_modulus_len

    # --- USRP parameters ---
    serial = "34414CA"  # Adjust to your USRP
    rx_gain = 70
    tx_gain = 80
    bandwidth = 250000
    sample_rate = 1e6
    tx_freq = 1010e6
    rx_freq = 990e6
    tx_ch_ID = 1
    rx_ch_ID = 0
    sf = [7]
    samplesBlockRec = 350000

    loradio = lora_transceiver.lora_transceiver(
        serial,
        rx_gain,
        tx_gain,
        bandwidth,
        rx_freq,
        tx_freq,
        sample_rate,
        rx_ch_ID,
        tx_ch_ID
    )
    rx_queues = loradio.rx_start(sf, samplesBlockRec)

    # Spawn THREADS for each SF
    readers = []
    for i in range(len(sf)):
        t = threading.Thread(target=pkt_reader, args=(rx_queues[i],), daemon=True)
        readers.append(t)
        t.start()

    print("[Receiver] Ready for MAVLink. Press Ctrl+C to stop.")

    try:
        for t in readers:
            t.join()
    except KeyboardInterrupt:
        print("[Receiver] Stopping...")


def human_readable_mavlink(msg):
    """Convert a MAVLink message object to human-readable command."""
    if msg.get_type() == "HEARTBEAT":
        armed = "ARMED" if (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) else "DISARMED"
        mode = mavutil.mode_string_v10(msg)
        return f"HEARTBEAT → {armed}, mode: {mode}"

    if msg.get_type() == "COMMAND_LONG":
        cmd = msg.command
        if cmd == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
            action = "ARM" if msg.param1 else "DISARM"
            return f"COMMAND → {action}"
        if cmd == mavutil.mavlink.MAV_CMD_NAV_TAKEOFF:
            return f"COMMAND → TAKEOFF to alt {msg.param7} m"
        if cmd == mavutil.mavlink.MAV_CMD_NAV_LAND:
            return f"COMMAND → LAND at lat {msg.param5}, lon {msg.param6}"
        return f"COMMAND_LONG → command={cmd}, params={[msg.param1, msg.param2, msg.param3, msg.param4, msg.param5, msg.param6, msg.param7]}"

    if msg.get_type() == "SET_POSITION_TARGET_GLOBAL_INT":
        return f"Move to lat={msg.lat_int/1e7}, lon={msg.lon_int/1e7}, alt={msg.alt} m"

    if msg.get_type() == "SET_MODE":
        mode_map = {
            0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO", 4: "GUIDED", 5: "LOITER",
            6: "RTL", 7: "CIRCLE", 9: "LAND", 11: "DRIFT", 13: "SPORT", 14: "FLIP",
            15: "AUTOTUNE", 16: "POSHOLD", 17: "BRAKE", 18: "THROW", 19: "AVOID_ADSB",
            20: "GUIDED_NOGPS", 21: "SMART_RTL", 22: "FLOWHOLD", 23: "FOLLOW",
            24: "ZIGZAG", 25: "SYSTEMID",
        }
        mode_name = mode_map.get(msg.custom_mode, f"UNKNOWN({msg.custom_mode})")
        return f"SET_MODE → {mode_name} (base_mode={msg.base_mode})"

    return f"{msg.get_type()} → {msg.to_dict()}"


def pkt_reader(pkt_queue):
    global enc_key_bytes, aes_key, got_key, rsa_modulus_len
    from config import KEYS_DIR

    priv_path = os.path.join(KEYS_DIR, "receiver_private.pem")
    if not os.path.exists(priv_path):
        raise FileNotFoundError(f"❌ Missing private key file: {priv_path}. Run generate_keys.py first.")

    with open(priv_path, "rb") as f:
        priv_key_bytes = f.read()
    rsa_key = RSA.import_key(priv_key_bytes)
    rsa_modulus_len = rsa_key.size_in_bytes()

    print(f"[Receiver] Using RSA key size: {rsa_key.size_in_bits()} bits → {rsa_modulus_len} bytes")

    receiver = Receiver(priv_key_bytes)
    partial_msgs = {}
    mav_parser = mavutil.mavlink.MAVLink(None)
    seen_packets = set()

    while True:
        pkt = pkt_queue.get()
        if not isinstance(pkt, lora.LoRaPacket):
            continue

        payload = pkt.payload.tobytes()
        seq = pkt.seqn
        pkt_sig = (seq, payload)

        if pkt_sig in seen_packets:
            continue
        seen_packets.add(pkt_sig)

        if not payload:
            continue

        header = payload[0]
        body = payload[1:]

        print(f"[Reader] LoRa pkt: len={len(payload)}, sf={pkt.SF}, seq={seq}, crc_ok={pkt.crc_ok}")

        # --- Step 1: AES Key ---
        if header == HEADER_KEY and not got_key:
            enc_key_bytes.extend(body)
            print(f"[Reader] Receiving AES key chunk: total={len(enc_key_bytes)}/{rsa_modulus_len}")

            if len(enc_key_bytes) >= rsa_modulus_len:
                enc_key_bytes = enc_key_bytes[:rsa_modulus_len]
                aes_key = receiver.decrypt_key(bytes(enc_key_bytes))
                if aes_key == 'BER':
                    print("🥷 HACKER HACKER HACKER")
                    enc_key_bytes = bytearray()
                    continue
                save_aes_key(aes_key)
                got_key = True
                print(f"[Receiver] ✅ AES key recovered and saved (len={len(aes_key)} bytes)")
                enc_key_bytes = bytearray()
            continue

        elif not got_key and len(enc_key_bytes) > 0:
            enc_key_bytes.extend(payload)
            print(f"[Reader] Receiving AES key chunk: total={len(enc_key_bytes)}/{rsa_modulus_len}")

            if len(enc_key_bytes) >= rsa_modulus_len:
                enc_key_bytes = enc_key_bytes[:rsa_modulus_len]
                aes_key = receiver.decrypt_key(bytes(enc_key_bytes))
                if aes_key == 'BER':
                    print("🥷 HACKER HACKER HACKER")
                    enc_key_bytes = bytearray()
                    continue
                save_aes_key(aes_key)
                got_key = True
                print(f"[Receiver] ✅ AES key recovered and saved (len={len(aes_key)} bytes)")
                enc_key_bytes = bytearray()
            continue

        # --- Step 2: MAVLink Data ---
        elif header == HEADER_DATA:
            aes_key = load_aes_key()
            if not aes_key:
                print("[Receiver] ❌ No AES key stored, cannot decrypt")
                continue

            buf = body
            while len(buf) >= 4:
                msg_len = int.from_bytes(buf[:4], "big")
                total_len = 4 + 16 + 16 + msg_len
                if len(buf) < total_len:
                    break

                nonce = buf[4:20]
                tag = buf[20:36]
                ciphertext = buf[36:total_len]

                try:
                    plaintext = decrypt_data(nonce, ciphertext, tag, aes_key)
                    hex_str = plaintext.hex(" ").upper()
                    mav_msg = mav_parser.parse_char(plaintext)
                    if mav_msg is not None:
                        print(f"[Receiver] ✅ {human_readable_mavlink(mav_msg)} | HEX={hex_str}")
                        print(f"[Receiver] ✅ data key recovered and saved (len={len(plaintext)} bytes)")
                except Exception:
                    print("❌ AES Mismatch, Payload Ignored")
                    # print(f"[Receiver] ❌ Decryption failed: {e}")

                buf = buf[total_len:]
            continue

        else:
            if header == HEADER_KEY:
                print("🥷 RSA KEY ALREADY RECEIVED, IGNORING")
                continue
            else:
                print("[Receiver] ❓ Unknown header, ignoring")
                continue


if __name__ == "__main__":
    main()
