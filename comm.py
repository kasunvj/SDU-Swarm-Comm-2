#!/usr/bin/env python3
"""
XBee Bidirectional Comm — with auto-reconnect
Usage: python3 comm.py <port> <receive_file> <send_file>
  e.g: python3 comm.py /dev/ttyUSB0 receive.txt send.txt

- Watches send.txt for content, transmits and clears it
- Listens on port, appends any received messages to receive.txt
- If the USB device drops and re-enumerates under a different name
  (e.g. ttyUSB0 -> ttyUSB1), automatically finds it and reconnects.
"""

import glob
import os
import re
import sys
import threading
import time
from datetime import datetime

import serial

BAUDRATE       = 9600
POLL_INTERVAL  = 0.01   # seconds
RECONNECT_WAIT = 0.5    # seconds between reconnect attempts


# ── Serial connection manager ──────────────────────────────────────────────
#
# Both threads share one of these instead of a raw serial.Serial object.
# On any SerialException, a thread calls reconnect(), which blocks until a
# usable serial port reappears (scanning for the same-style device node if
# the original one vanished) and reopens the connection. The lock protects
# against both threads reconnecting at once.

class SerialManager:
    def __init__(self, port, baudrate):
        self.baudrate = baudrate
        self.port_pattern = self._pattern_for(port)
        self._lock = threading.Lock()
        self._ser = None
        self._discard_next_rx = False
        self._connect(port)

    @staticmethod
    def _pattern_for(port):
        # /dev/ttyUSB0 -> /dev/ttyUSB*, /dev/ttyACM3 -> /dev/ttyACM*, etc.
        m = re.match(r'^(.*?)(\d+)$', port)
        return (m.group(1) + '*') if m else port

    def _candidate_ports(self, preferred):
        candidates = []
        if preferred and os.path.exists(preferred):
            candidates.append(preferred)
        for p in sorted(glob.glob(self.port_pattern)):
            if p not in candidates:
                candidates.append(p)
        return candidates

    def _connect(self, preferred):
        while True:
            for candidate in self._candidate_ports(preferred):
                try:
                    ser = serial.Serial(candidate, self.baudrate, timeout=1)
                    # Discard anything queued during the disconnect gap —
                    # a partial line from the old connection can otherwise
                    # get glued onto the first line read on the new one.
                    time.sleep(0.05)  # let the OS-level buffer settle
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    self._ser = ser
                    self._discard_next_rx = True
                    print(f"  Connected: {candidate}")
                    return
                except serial.SerialException:
                    continue
            print(f"  No device matching '{self.port_pattern}' found, retrying...")
            time.sleep(RECONNECT_WAIT)

    def get(self):
        """Return the current live serial.Serial (may block during a reconnect)."""
        with self._lock:
            return self._ser

    def pop_discard_flag(self):
        """Return True (once) if the connection was just re-established,
        meaning the caller should throw away the next read as possibly
        corrupted/merged with leftover data from the old connection."""
        with self._lock:
            flag = self._discard_next_rx
            self._discard_next_rx = False
            return flag

    def reconnect(self, failed_port_hint=None):
        """Drop the dead connection and block until a new one is up."""
        with self._lock:
            try:
                if self._ser is not None:
                    self._ser.close()
            except Exception:
                pass
            print("  Connection lost — searching for device...")
            self._connect(failed_port_hint)


# ── Receiver thread ─────────────────────────────────────────────────────────

def receiver(mgr, rx_file):
    while True:
        ser = mgr.get()
        try:
            line = ser.readline().decode(errors='ignore').strip()

            if mgr.pop_discard_flag():
                if line:
                    print(f"  (discarded post-reconnect fragment: {line!r})")
                continue

            if not line:
                continue

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            entry = f"[{timestamp}] {line}"

            with open(rx_file, 'a') as f:
                f.write(entry + '\n')

            print(f"  RX: {entry}")

        except serial.SerialException as e:
            print(f"  ERROR (receiver): {e}")
            mgr.reconnect(ser.port if ser else None)
        except OSError as e:
            # covers "device disappeared" errors that surface as OSError
            print(f"  ERROR (receiver): {e}")
            mgr.reconnect(ser.port if ser else None)


# ── Transmitter thread ────────────────────────────────────────────────────────

def transmitter(mgr, tx_file):
    work_file = tx_file + ".sending"
    while True:
        try:
            if not os.path.exists(tx_file) or os.path.getsize(tx_file) == 0:
                time.sleep(POLL_INTERVAL)
                continue

            os.replace(tx_file, work_file)        # atomic claim — new writes go to a fresh tx_file
            with open(work_file, 'r') as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            os.remove(work_file)

            for line in lines:
                ser = mgr.get()
                try:
                    ser.write((line + '\n').encode())
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    print(f"  TX: [{timestamp}] {line}")
                except (serial.SerialException, OSError) as e:
                    print(f"  ERROR (transmitter): {e}")
                    mgr.reconnect(ser.port if ser else None)
                    # keep this line for retry on the reconnected port
                    ser = mgr.get()
                    try:
                        ser.write((line + '\n').encode())
                    except Exception as e2:
                        print(f"  ERROR (transmitter retry failed): {e2}")
                time.sleep(0.1)
        except FileNotFoundError:
            pass
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

    # Open serial port (blocks/retries until a matching device is found)
    mgr = SerialManager(port, BAUDRATE)

    print(f"\n  Port pattern : {mgr.port_pattern}")
    print(f"  Receive      : {rx_file}")
    print(f"  Send         : {tx_file}")
    print(f"  Press Ctrl+C to stop\n")

    # Start threads
    rx_thread = threading.Thread(target=receiver,     args=(mgr, rx_file), daemon=True)
    tx_thread = threading.Thread(target=transmitter,  args=(mgr, tx_file), daemon=True)

    rx_thread.start()
    tx_thread.start()

    try:
        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        print(f"\n  Stopped.")

    finally:
        ser = mgr.get()
        try:
            if ser:
                ser.close()
        except Exception:
            pass
        print("  Port closed.")


if __name__ == '__main__':
    main()