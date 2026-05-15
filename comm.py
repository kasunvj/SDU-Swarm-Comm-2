#!/usr/bin/env python3
"""
XBee Bidirectional Comm
Usage: python3 comm.py <port> <receive_file> <send_file>
  e.g: python3 comm.py /dev/ttyUSB0 receive.txt send.txt

- Watches send.txt for content, transmits and clears it
- Listens on port, appends any received messages to receive.txt
"""

import serial
import sys
import os
import time
import threading
from datetime import datetime

BAUDRATE      = 9600
POLL_INTERVAL = 0.5


# ── Receiver thread ───────────────────────────────────────────────────────────

def receiver(ser, rx_file):
    while True:
        try:
            line = ser.readline().decode(errors='ignore').strip()
            if not line:
                continue

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            entry = f"[{timestamp}] {line}"

            with open(rx_file, 'a') as f:
                f.write(entry + '\n')

            print(f"  RX: {entry}")

        except serial.SerialException as e:
            print(f"  ERROR (receiver): {e}")
            break


# ── Transmitter thread ────────────────────────────────────────────────────────

def transmitter(ser, tx_file):
    while True:
        try:
            with open(tx_file, 'r') as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]

            if not lines:
                time.sleep(POLL_INTERVAL)
                continue

            all_sent = True
            for line in lines:
                try:
                    ser.write((line + '\n').encode())
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"  TX: [{timestamp}] {line}")
                    time.sleep(0.1)
                except serial.SerialException as e:
                    print(f"  ERROR (transmitter): {e}")
                    all_sent = False
                    break

            if all_sent:
                with open(tx_file, 'w') as f:
                    f.write('')
                print(f"  Send file cleared.\n")
            else:
                print(f"  TX error — send file NOT cleared, will retry.\n")

        except Exception as e:
            print(f"  ERROR (transmitter): {e}")

        time.sleep(POLL_INTERVAL)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 4:
        print("Usage: python3 comm.py <port> <receive_file> <send_file>")
        print("  e.g: python3 comm.py /dev/ttyUSB0 receive.txt send.txt")
        sys.exit(1)

    port    = sys.argv[1]
    rx_file = sys.argv[2]
    tx_file = sys.argv[3]

    # Create files if they don't exist
    for filepath in [rx_file, tx_file]:
        if not os.path.exists(filepath):
            open(filepath, 'w').close()
            print(f"  Created '{filepath}'")

    # Open serial port
    try:
        ser = serial.Serial(port, BAUDRATE, timeout=1)
    except serial.SerialException as e:
        print(f"  ERROR: Cannot open {port} — {e}")
        sys.exit(1)

    print(f"\n  Port     : {port}")
    print(f"  Receive  : {rx_file}")
    print(f"  Send     : {tx_file}")
    print(f"  Press Ctrl+C to stop\n")

    # Start threads
    rx_thread = threading.Thread(target=receiver,     args=(ser, rx_file), daemon=True)
    tx_thread = threading.Thread(target=transmitter,  args=(ser, tx_file), daemon=True)

    rx_thread.start()
    tx_thread.start()

    try:
        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        print(f"\n  Stopped.")

    finally:
        ser.close()
        print("  Port closed.")


if __name__ == '__main__':
    main()