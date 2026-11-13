#!/usr/bin/env python3
import uhd
import numpy as np
import time

# ============ USER SETTINGS ============
FILE_PATH = "a3with_ency_without_hop_200.raw"
TX_FREQ = 910e6           # 910 MHz
TX_RATE = 2e6             # 2 MSPS (match your GQRX sample rate exactly!)
TX_GAIN = 70              # Adjust between 0-76 dB depending on need
LOOP = True             # True → continuously replay file in loop
# =======================================

def main():
    print("Loading recorded IQ data...")
    # GQRX stores raw data as interleaved float32 IQ: [I0, Q0, I1, Q1, ...]
    iq_data = np.fromfile(FILE_PATH, dtype=np.float32)
    if len(iq_data) == 0:
        print("Error: File is empty or path is incorrect.")
        return
    # Convert to complex64
    iq_complex = iq_data[0::2] + 1j * iq_data[1::2]
    print(f"Loaded {len(iq_complex)} complex samples.")

    # Initialize USRP
    usrp = uhd.usrp.MultiUSRP()
    usrp.set_tx_rate(TX_RATE)
    usrp.set_tx_freq(uhd.types.TuneRequest(TX_FREQ))
    usrp.set_tx_gain(TX_GAIN)
    usrp.set_tx_antenna("TX/RX")

    print(f"Transmitting at {TX_FREQ/1e6} MHz, {TX_RATE/1e6} MSPS")

    # Setup streamer
    st_args = uhd.usrp.StreamArgs("fc32", "sc16")  # Input type: complex float32, wire type: int16
    tx_streamer = usrp.get_tx_stream(st_args)
    buffer_samps = 1024

    # Metadata
    md = uhd.types.TXMetadata()
    md.start_of_burst = True
    md.end_of_burst = False

    try:
        while True:
            idx = 0
            total_len = len(iq_complex)
            while idx < total_len:
                send_buffer = iq_complex[idx: idx + buffer_samps]
                if len(send_buffer) == 0:
                    break
                num_sent = tx_streamer.send(send_buffer, md)
                md.start_of_burst = False
                idx += num_sent

            if not LOOP:
                break

        # End of burst
        md.end_of_burst = True
        tx_streamer.send(np.zeros(1, dtype=np.complex64), md)

    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        print("Transmission complete.")

if __name__ == "__main__":
    main()
