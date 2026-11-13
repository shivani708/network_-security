# Attacker-Side Replay Scripts

These are the **intruder/attacker** tools used to test the replay-attack protection in Chapter 5 of the project. Each script loads a GQRX IQ recording of a previously captured encrypted MAVLink command and **re-transmits it** on a USRP B210, posing as the original sender. The receiver is expected to detect the replayed nonce / sequence number and reject the packet before decryption (see the two-layer replay protection in the main [README](../README.md)).

> ⚠️ **Authorised lab testing only.** These scripts transmit RF. They were run in a controlled environment at TiHAN, IIT Hyderabad to validate the receiver's own defences. Re-transmitting captured signals on live radio bands is illegal and unsafe outside an authorised, isolated setup.

## Scripts

| Script | Capture replayed | TX freq | Sample rate | TX gain | Notes |
|---|---|---|:---:|:---:|:---:|
| `a1.py` | `gqrx_...910000199...fc.raw` | 910.1 MHz | 2 MS/s | 70 | Simple fixed-config loop replay |
| `a2.py` | configurable (`--file`, `--freq`, …) | 910.0 MHz | 2 MS/s | 80 | Auto-detects float32 vs int16 IQ; argparse CLI; chunked streaming |
| `a3.py` | `a3with_ency_without_hop_200.raw` | 910.0 MHz | 2 MS/s | 70 | Encrypted command, no frequency hopping |
| `a4.py` | `gqrx_20260228...250000...fc.raw` | 910.0 MHz | 250 kS/s | 70 | Narrower-band capture |
| `a5.py` | `gqrx_20260307...2000000...fc.raw` | 910.0 MHz | 2 MS/s | 90 | Higher TX gain |

All scripts read interleaved float32 IQ (`[I0, Q0, I1, Q1, ...]`, the GQRX raw format), convert to `complex64`, and stream to the USRP with `fc32`/`sc16` streamer args, looping until stopped (Ctrl+C).

## Usage

```bash
# a2.py is the flexible one:
python a2.py --file capture.raw --freq 910e6 --rate 2e6 --gain 80 --loop

# a1/a3/a4/a5: edit the FILE_PATH / TX_* constants at the top, then:
python a3.py
```

## IQ recordings not included

The `.raw` GQRX captures these scripts replay (70 MB and 223 MB) are **not in this repository** — they exceed GitHub's file-size limit and are git-ignored. Point each script's `FILE_PATH` (or `--file`) at your own recording. Record one with GQRX, or capture a live encrypted command off the air in your own authorised setup.
