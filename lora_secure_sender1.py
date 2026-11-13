import os
import threading
import queue
import numpy as np
from flask import Flask, jsonify
from flask_cors import CORS
from pymavlink import mavutil
import lora_transceiver
import lora_utils
from aes_utils import generate_aes_key, encrypt_data
from file_transfer import Sender
from config import AES_KEY_SIZE, KEYS_DIR
from pathlib import Path
from time import sleep
from Crypto.PublicKey import RSA

# Silence UHD spam logs
os.environ.setdefault("UHD_LOG_LEVEL", "error")

# --- Headers ---
HEADER_KEY = 0xA1
HEADER_DATA = 0xB1

# ===================== MAVLINK SETUP ===================== #
class DummyFile:
    def write(self, data):
        return len(data)


mav = mavutil.mavlink.MAVLink(DummyFile())
mav.srcSystem = 254
mav.srcComponent = 1
target_system = 1
target_component = 1
ID = 0


def to_raw_bytes(msg):
    return msg.pack(mav)


def arm_vehicle():
    return mav.command_long_encode(
        target_system=target_system,
        target_component=target_component,
        command=mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        confirmation=0,
        param1=1, param2=0, param3=0, param4=0,
        param5=0, param6=0, param7=0
    )


def disarm_vehicle():
    return mav.command_long_encode(
        target_system=target_system,
        target_component=target_component,
        command=mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        confirmation=0,
        param1=0, param2=0, param3=0, param4=0,
        param5=0, param6=0, param7=0
    )


def takeoff_10(mav):
    return mav.command_long_encode(
        target_system=target_system,
        target_component=target_component,
        command=mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
        confirmation=0,
        param1=0, param2=0, param3=0, param4=0,
        param5=0, param6=0, param7=100
    )


def mode_guided(mav):
    return mav.set_mode_encode(
        target_system=target_system,
        base_mode=0,
        custom_mode=4
    )


def mode_land(mav):
    return mav.set_mode_encode(
        target_system=target_system,
        base_mode=0,
        custom_mode=9
    )


def motor_test():
    return mav.command_long_encode(
        target_system=target_system,
        target_component=target_component,
        command=mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST,
        confirmation=0,
        param1=0, param2=1, param3=50, param4=3,
        param5=0, param6=0, param7=0
    )


# ===================== FLASK SETUP ===================== #
app = Flask(__name__)
CORS(app)
command_buffer = queue.Queue()

# ===================== USRP / LORA SETUP ===================== #
serial = "34414C5"  # adjust for your USRP
rx_gain = 70
tx_gain = 80
bandwidth = 250000
sample_rate = 1e6
tx_freq = 990e6
rx_freq = 1010e6
tx_ch_ID = 1
rx_ch_ID = 0
SF = 7
sleep_time = 1
packet_size = 250
srcID = 0
dstID = 1
CR = 1

loradio = lora_transceiver.lora_transceiver(
    serial, rx_gain, tx_gain, bandwidth,
    rx_freq, tx_freq, sample_rate,
    rx_ch_ID, tx_ch_ID
)

tx_queue = loradio.tx_start(sleep_time=sleep_time, verbose=True)

# ===================== ENCRYPTION ===================== #
pub_path = Path(KEYS_DIR) / "receiver_public.pem"
if not pub_path.exists():
    raise FileNotFoundError(f"❌ Missing public key: {pub_path}. Copy it from receiver machine.")

with open(pub_path, "rb") as f:
    pub_key_bytes = f.read()

sender = Sender(pub_key_bytes)

# Generate AES session key and encrypt it with RSA
aes_key = generate_aes_key(AES_KEY_SIZE)
print("DEBUG: raw AES key length (bytes):", len(aes_key))
print("DEBUG: raw AES key (hex):", aes_key.hex())

# Encrypt AES key with RSA
enc_key = sender.encrypt_key(aes_key)
print("DEBUG: RSA-encrypted key length (bytes):", len(enc_key))
print("DEBUG: RSA-encrypted key (hex prefix):", enc_key[:16].hex())

# Split encrypted AES key into LoRa-safe packets with header
key_array = np.frombuffer(bytes([HEADER_KEY]) + enc_key, dtype=np.uint8)
key_packets = lora_utils.pack_lora_data(
    key_array, SF, bandwidth, packet_size,
    srcID, dstID, extended_sqn=False, CR=CR
)

for pack in key_packets:
    tx_queue.put(pack)
    print(f"📡 Sending AES key packet | Header: {HEADER_KEY}")
    sleep(0.1)

print(f"📡 Sent {len(key_packets)} packets for AES session key")
print("[Sender] Encrypted AES key length:", len(enc_key))
print("[Sender] Encrypted AES key (hex prefix):", enc_key[:16].hex())

# ===================== TX THREAD ===================== #
def tx_thread():
    while True:
        msg_bytes = command_buffer.get()
        if not aes_key:
            print("⚠️ AES key not ready, skipping command")
            continue

        # Encrypt MAVLink command with AES-GCM
        nonce, ciphertext, tag = encrypt_data(msg_bytes, aes_key)
        print(f"DEBUG: AES-GCM nonce: {nonce.hex()}")
        print(f"DEBUG: AES-GCM tag: {tag.hex()}")
        print(f"DEBUG: AES-GCM ciphertext length: {len(ciphertext)}")

        # Construct packet with HEADER_DATA
        enc_blob = (
            bytes([HEADER_DATA]) +
            len(ciphertext).to_bytes(4, "big") +
            nonce + tag + ciphertext
        )

        data_array = np.frombuffer(enc_blob, dtype=np.uint8)

        # Pack into LoRa packets
        data_packets = lora_utils.pack_lora_data(
            data_array, SF, bandwidth, packet_size,
            srcID, dstID, extended_sqn=False, CR=CR
        )

        for pack in data_packets:
            tx_queue.put(pack)
            print(f"📡 Sending MAVLink packet | Header: {HEADER_DATA} | Packet len: {len(pack)}")

        print(f"📡 Sent {len(data_packets)} packets for MAVLink command")


# ===================== FLASK ENDPOINTS ===================== #
@app.route('/arm', methods=['GET'])
def arm():
    command_buffer.put(to_raw_bytes(arm_vehicle()))
    return jsonify({"status": "ARM command queued"}), 200


@app.route('/disarm', methods=['GET'])
def disarm():
    command_buffer.put(to_raw_bytes(disarm_vehicle()))
    return jsonify({"status": "DISARM command queued"}), 200


@app.route('/takeoff', methods=['GET'])
def takeoff():
    command_buffer.put(to_raw_bytes(takeoff_10(mav)))
    return jsonify({"status": "Takeoff command queued"}), 200


@app.route('/mode/guided', methods=['GET'])
def set_mode_guided():
    command_buffer.put(to_raw_bytes(mode_guided(mav)))
    return jsonify({"status": "Mode GUIDED queued"}), 200


@app.route('/mode/land', methods=['GET'])
def set_mode_land():
    command_buffer.put(to_raw_bytes(mode_land(mav)))
    return jsonify({"status": "Mode LAND queued"}), 200


@app.route('/motor_test', methods=['GET'])
def motor_test_route():
    command_buffer.put(to_raw_bytes(motor_test()))
    return jsonify({"status": "Motor test queued"}), 200


@app.route('/status', methods=['GET'])
def get_status():
    return jsonify({
        "drone_connected": True,
        "connection_type": "LoRa Radio",
        "target_system": target_system,
        "server_status": "running",
        "radio_status": "connected"
    }), 200


@app.route('/connect', methods=['GET'])
def connect_drone():
    return jsonify({
        "status": "Connected via LoRa Radio",
        "connection_type": "LoRa Radio",
        "target_system": target_system,
        "node_id": ID
    }), 200


# ===================== MAIN ===================== #
if __name__ == "__main__":
    thread1 = threading.Thread(target=tx_thread, daemon=True)
    thread1.start()
    app.run(host='0.0.0.0', port=5000)
    thread1.join()
