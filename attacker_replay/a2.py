#!/usr/bin/env python3
"""
Replay a GQRX raw IQ file (interleaved IQ) exactly on a USRP (B210) using UHD.

Assumptions (change below if different):
 - File: interleaved IQ
 - Preferred dtype: float32 (I,Q,I,Q,...)
 - Default sample rate and center freq parsed from your filename but overrideable below.
"""
import os
import numpy as np
import uhd
import time
import argparse
import sys

# ------------- Config (edit as needed) -------------
FILE_PATH = "gqrx_20251103_061431_910000199_2000000_fc.raw"
# Parsed from your filename earlier, change if you recorded with different settings:
DEFAULT_TX_FREQ = 910.000199e6   # Hz
DEFAULT_TX_RATE = 2e6            # S/s
TX_GAIN = 80                     # dB (adjust to your regulatory/power needs)
ANTENNA = "TX/RX"                # change if your board uses another string
LOOP = True                     # True -> continuous replay
CHUNK_COMPLEX = 131072           # number of complex samples per send (tune if necessary)
TIME_BETWEEN_CHUNKS = 0.0        # small sleep between chunks (usually 0)
# ------------- end config --------------------------------

def detect_format_and_create_generator(path, chunk_complex=CHUNK_COMPLEX):
    filesize = os.path.getsize(path)
    # We'll prefer float32 if the small-sample stats look normalized.
    with open(path, "rb") as f:
        head = f.read(4096)
    # try float32 interpretation
    try:
        arrf = np.frombuffer(head, dtype=np.float32)
        if arrf.size >= 2:
            complex_f = arrf[0::2] + 1j*arrf[1::2]
            mean_abs = np.mean(np.abs(complex_f))
            max_abs = np.max(np.abs(complex_f))
        else:
            mean_abs = 0
            max_abs = 0
    except Exception:
        mean_abs = 1e9
        max_abs = 1e9

    # Heuristic: float32 IQ usually has small magnitudes (<= ~1.0 often << 1)
    prefer_float32 = (mean_abs < 10.0)

    if prefer_float32:
        dtype = np.float32
        samples_per_complex = 2 * 4  # bytes
        interpret = "float32"
    else:
        # fallback to int16
        dtype = np.int16
        samples_per_complex = 2 * 2
        interpret = "int16"

    total_complex = os.path.getsize(path) // samples_per_complex

    def generator():
        # yield numpy arrays of dtype complex64
        with open(path, "rb") as f:
            while True:
                # read N complex samples => 2*N scalars
                nscalars = chunk_complex * 2
                buf = f.read(nscalars * np.dtype(dtype).itemsize)
                if not buf or len(buf) == 0:
                    break
                arr = np.frombuffer(buf, dtype=dtype)
                if dtype == np.int16:
                    # convert to float in range [-1,1) assuming full-scale int16
                    fx = arr.astype(np.float32) / 32768.0
                else:
                    fx = arr.astype(np.float32)
                if fx.size % 2 != 0:
                    # drop last incomplete sample if present
                    fx = fx[:-1]
                cx = fx[0::2] + 1j * fx[1::2]
                yield cx.astype(np.complex64)
    return interpret, total_complex, generator

def main():
    parser = argparse.ArgumentParser(description="Replay raw IQ to USRP (B210)")
    parser.add_argument("--file", "-f", default=FILE_PATH)
    parser.add_argument("--freq", type=float, default=DEFAULT_TX_FREQ)
    parser.add_argument("--rate", type=float, default=DEFAULT_TX_RATE)
    parser.add_argument("--gain", type=float, default=TX_GAIN)
    parser.add_argument("--antenna", default=ANTENNA)
    parser.add_argument("--loop", action="store_true", help="loop playback")
    parser.add_argument("--chunk", type=int, default=CHUNK_COMPLEX, help="complex samples per send")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print("File not found:", args.file); sys.exit(1)

    interpret, total_complex, gen = detect_format_and_create_generator(args.file, chunk_complex=args.chunk)
    duration_s = total_complex / args.rate
    print(f"File: {args.file}")
    print(f"Detected interpretation: {interpret}")
    print(f"Complex samples (approx): {total_complex:,}")
    print(f"Estimated duration @ {args.rate/1e6:.6f} MS/s: {duration_s:.3f} s")
    print(f"Will transmit at {args.freq/1e6:.6f} MHz, rate {args.rate/1e6:.6f} MS/s, gain {args.gain} dB\n")

    # create USRP
    print("Creating USRP device...")
    usrp = uhd.usrp.MultiUSRP()   # uses default args; set address string if multiple devices
    usrp.set_tx_rate(args.rate)
    usrp.set_tx_freq(uhd.types.TuneRequest(args.freq))
    usrp.set_tx_gain(args.gain)
    try:
        usrp.set_tx_antenna(args.antenna)
    except Exception:
        pass

    # streamer: host format complex64 (fc32), wire format sc16 (int16) is common
    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    tx_streamer = usrp.get_tx_stream(st_args)
    md = uhd.types.TXMetadata()

    # Playback loop
    try:
        while True:
            iterator = gen()
            md.start_of_burst = True
            md.end_of_burst = False
            for chunk in iterator:
                # chunk is np.complex64
                # send returns number of samples actually consumed; default timeout is big
                num_sent = tx_streamer.send(chunk, md)
                # after first send, clear start_of_burst
                if md.start_of_burst:
                    md.start_of_burst = False
                # small optional pause
                if TIME_BETWEEN_CHUNKS > 0:
                    time.sleep(TIME_BETWEEN_CHUNKS)
            # end of file -> send zero-length end-of-burst
            md.end_of_burst = True
            tx_streamer.send(np.zeros(1, dtype=np.complex64), md)
            md.end_of_burst = False
            if not args.loop and not LOOP:
                break
            print("Looping playback...")
    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        print("Done.")

if __name__ == "__main__":
    main()
