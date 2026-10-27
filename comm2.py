#!/usr/bin/env python3
"""
XBee Bidirectional Comm — framed binary drone-state packets, with auto-reconnect
Usage: python3 comm.py <port> <receive_file> <send_file>
  e.g: python3 comm.py /dev/ttyUSB0 receive.txt send.txt

- Watches send.txt for lines of the form
      id,px,py,pz,vx,vy,vz          (metres, m/s; id 0-99)
  encodes each line into an 18-byte frame, transmits it, and clears the file.
- Listens on the port, validates and decodes every frame, and appends it to
  receive.txt in the same text format:
      [timestamp] id,px,py,pz,vx,vy,vz
- If the USB device drops and re-enumerates under a different name
  (e.g. ttyUSB0 -> ttyUSB1), automatically finds it and reconnects.

Frame on the wire (18 bytes):

    +------------------------------------------------+------+
    |  COBS( payload[13] | seq[1] | crc16[2] )  17 B | 0x00 |
    +------------------------------------------------+------+

  payload (13 bytes, little-endian):
    Byte   0      : id    uint8   (0-99)
    Bytes  1-6    : px,py,pz      int16   cm
    Bytes  7-12   : vx,vy,vz      int16   cm/s
  seq    : uint8, counter per drone id, wraps 255 -> 0
  crc16  : CRC-16/CCITT-FALSE over payload + seq, little-endian
  COBS   : Consistent Overhead Byte Stuffing. Removes every 0x00 from the
           data (cost: +1 byte), so 0x00 can only ever mean "end of frame".
  0x00   : frame delimiter

Range: +/-327.67 m and +/-327.67 m/s, resolution 1 cm and 1 cm/s.

Why this is reliable:
  - Framing never depends on timing or on the data: the receiver splits the
    byte stream at 0x00, and 0x00 cannot occur inside a frame.
  - After any corruption, lost byte or mid-frame start, the receiver resyncs
    at the very next 0x00. At most one frame is lost.
  - CRC-16 rejects frames whose bytes were altered or truncated.
  - The sequence number reveals lost, duplicated and out-of-order frames, and
    stale (older) frames are dropped so the controller never uses old state.
"""

import binascii
import glob
import os
import re
import struct
import sys
import threading
import time
from datetime import datetime

import serial

BAUDRATE       = 9600
POLL_INTERVAL  = 0.01   # seconds
RECONNECT_WAIT = 0.5    # seconds between reconnect attempts
TX_SPACING     = 0.1    # seconds between transmitted frames (send rate limit)


# ── Payload encoding / decoding (13 bytes) ──────────────────────────────────

PAYLOAD_FMT  = "<B6h"                          # 1 x uint8 + 6 x int16, no padding
PAYLOAD_SIZE = struct.calcsize(PAYLOAD_FMT)    # 13 bytes
SCALE        = 100                             # m -> cm, m/s -> cm/s
INT16_MIN, INT16_MAX = -32768, 32767
ID_MAX       = 99


def _to_int16(value):
    """Scale a value in SI units to int16, clamping to the representable range."""
    raw = int(round(value * SCALE))
    return max(INT16_MIN, min(INT16_MAX, raw))


def encode(drone_id, pos, vel):
    """(id, (px,py,pz) [m], (vx,vy,vz) [m/s]) -> 13-byte payload."""
    if not 0 <= drone_id <= ID_MAX:
        raise ValueError(f"drone_id must be 0-{ID_MAX}, got {drone_id}")
    if len(pos) != 3 or len(vel) != 3:
        raise ValueError("pos and vel must each have 3 elements")
    return struct.pack(PAYLOAD_FMT, drone_id,
                       *(_to_int16(p) for p in pos),
                       *(_to_int16(v) for v in vel))


def decode(payload):
    """13-byte payload -> (id, (px,py,pz) [m], (vx,vy,vz) [m/s])."""
    if len(payload) != PAYLOAD_SIZE:
        raise ValueError(f"payload must be {PAYLOAD_SIZE} bytes, got {len(payload)}")
    drone_id, *raw = struct.unpack(PAYLOAD_FMT, payload)
    if drone_id > ID_MAX:
        raise ValueError(f"invalid drone_id {drone_id}")
    pos = tuple(r / SCALE for r in raw[:3])
    vel = tuple(r / SCALE for r in raw[3:])
    return drone_id, pos, vel


# ── Framing: seq + CRC-16 + COBS + 0x00 delimiter (18 bytes) ────────────────

DELIM      = 0x00
INNER_SIZE = PAYLOAD_SIZE + 1 + 2              # payload + seq + crc = 16 bytes
FRAME_SIZE = INNER_SIZE + 1 + 1                # + COBS overhead + delimiter = 18 bytes


def crc16(data):
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). crc16(b'123456789') == 0x29B1."""
    return binascii.crc_hqx(data, 0xFFFF)


def cobs_encode(data):
    """Return data with all 0x00 bytes removed via COBS (adds 1 byte for < 254 bytes)."""
    out = bytearray([0])           # placeholder for the first code byte
    code_idx, code = 0, 1
    for b in data:
        if b == 0:
            out[code_idx] = code
            code_idx, code = len(out), 1
            out.append(0)
        else:
            out.append(b)
            code += 1
            if code == 0xFF:
                out[code_idx] = code
                code_idx, code = len(out), 1
                out.append(0)
    out[code_idx] = code
    return bytes(out)


def cobs_decode(data):
    """Inverse of cobs_encode. Raises ValueError on malformed input."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        code = data[i]
        if code == 0:
            raise ValueError("zero byte inside COBS data")
        if i + code > n and code != 1:
            raise ValueError("COBS block runs past end of frame")
        out += data[i + 1:i + code]
        i += code
        if code != 0xFF and i < n:
            out.append(0)
    return bytes(out)


def build_frame(payload, seq):
    """13-byte payload + seq -> 18-byte frame ready to write to the serial port."""
    inner = payload + bytes([seq & 0xFF])
    inner += struct.pack("<H", crc16(inner))
    return cobs_encode(inner) + bytes([DELIM])


def parse_frame(body):
    """Frame body (bytes between delimiters, delimiter excluded) -> (payload, seq).
    Raises ValueError if the frame is malformed or fails the CRC check."""
    inner = cobs_decode(body)
    if len(inner) != INNER_SIZE:
        raise ValueError(f"wrong length {len(inner)} (expected {INNER_SIZE})")
    data, (rx_crc,) = inner[:-2], struct.unpack("<H", inner[-2:])
    if crc16(data) != rx_crc:
        raise ValueError("CRC mismatch")
    return data[:PAYLOAD_SIZE], data[PAYLOAD_SIZE]


class FrameReader:
    """Accumulates raw serial bytes and yields complete frame bodies split at 0x00."""

    MAX_BODY = FRAME_SIZE - 1      # 17 bytes; anything longer is garbage

    def __init__(self):
        self._buf = bytearray()
        self._overflowed = False

    def reset(self):
        self._buf.clear()
        self._overflowed = False

    def feed(self, data):
        """Feed raw bytes. Returns (bodies, n_garbage_bytes_discarded)."""
        bodies, garbage = [], 0
        for b in data:
            if b == DELIM:
                if self._overflowed:
                    garbage += len(self._buf)
                elif self._buf:
                    bodies.append(bytes(self._buf))
                self._buf.clear()
                self._overflowed = False
            elif self._overflowed:
                garbage += 1
            else:
                self._buf.append(b)
                if len(self._buf) > self.MAX_BODY:
                    # No delimiter where one must be: discard until the next 0x00.
                    garbage += len(self._buf)
                    self._buf.clear()
                    self._overflowed = True
        return bodies, garbage


class SeqTracker:
    """Per-sender sequence checking. Accepts new frames, drops duplicates and
    stale (older) ones, counts lost frames. Resyncs if a sender restarts."""

    RESYNC_AFTER = 3               # consecutive "stale" frames => sender restarted

    def __init__(self):
        self._last = {}            # drone_id -> last accepted seq
        self._stale_run = {}       # drone_id -> consecutive stale count

    def reset(self):
        self._last.clear()
        self._stale_run.clear()

    def check(self, drone_id, seq):
        """Returns (accept: bool, note: str or None)."""
        if drone_id not in self._last:
            self._last[drone_id] = seq
            self._stale_run[drone_id] = 0
            return True, None
        diff = (seq - self._last[drone_id]) & 0xFF
        if diff == 0:
            return False, "duplicate"
        if diff > 128:             # seq is behind the last accepted one
            self._stale_run[drone_id] += 1
            if self._stale_run[drone_id] < self.RESYNC_AFTER:
                return False, "stale/out-of-order"
            note = "sender restarted, resynced"
        else:
            note = f"{diff - 1} frame(s) lost" if diff > 1 else None
        self._last[drone_id] = seq
        self._stale_run[drone_id] = 0
        return True, note


# ── Text formats for send.txt / receive.txt ─────────────────────────────────

def parse_tx_line(line):
    """'id,px,py,pz,vx,vy,vz' -> (id, pos, vel). Raises ValueError if malformed."""
    parts = [p.strip() for p in line.split(',')]
    if len(parts) != 7:
        raise ValueError(f"expected 7 comma-separated values, got {len(parts)}")
    drone_id = int(parts[0])
    vals = [float(p) for p in parts[1:]]
    return drone_id, vals[:3], vals[3:]


def format_state(drone_id, pos, vel):
    """(id, pos, vel) -> 'id,px,py,pz,vx,vy,vz' with 1 cm (2 decimal) precision."""
    return f"{drone_id:02d}," + ",".join(f"{v:.2f}" for v in (*pos, *vel))


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
        self._reconnected = False
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
                    time.sleep(0.05)  # let the OS-level buffer settle
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    self._ser = ser
                    self._reconnected = True
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

    def pop_reconnected_flag(self):
        """Return True (once) if the connection was just (re-)established, so the
        receiver can throw away any half-assembled frame from the old connection."""
        with self._lock:
            flag = self._reconnected
            self._reconnected = False
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
    reader = FrameReader()
    seqs = SeqTracker()
    while True:
        ser = mgr.get()
        try:
            data = ser.read(ser.in_waiting or 1)   # blocks up to the port timeout

            if mgr.pop_reconnected_flag():
                # A partial frame from the old connection must not be glued onto
                # bytes from the new one. Everything resyncs at the next 0x00.
                reader.reset()

            if not data:
                continue

            bodies, garbage = reader.feed(data)
            if garbage:
                print(f"  (discarded {garbage} unframed byte(s), resyncing)")

            for body in bodies:
                try:
                    payload, seq = parse_frame(body)
                    drone_id, pos, vel = decode(payload)
                except ValueError as e:
                    print(f"  (dropped frame: {e}: {body.hex(' ')})")
                    continue

                accept, note = seqs.check(drone_id, seq)
                if note:
                    print(f"  (id {drone_id:02d} seq {seq}: {note})")
                if not accept:
                    continue

                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                entry = f"[{timestamp}] {format_state(drone_id, pos, vel)}"

                with open(rx_file, 'a') as f:
                    f.write(entry + '\n')

                print(f"  RX: {entry}  (seq {seq})")

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
    seqs = {}                      # drone_id -> next seq (receiver tracks seq per id too)
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
                try:
                    drone_id, pos, vel = parse_tx_line(line)
                    payload = encode(drone_id, pos, vel)
                except ValueError as e:
                    print(f"  (skipped bad send line {line!r}: {e})")
                    continue

                seq = seqs.get(drone_id, 0)
                seqs[drone_id] = (seq + 1) & 0xFF
                frame = build_frame(payload, seq)
                ser = mgr.get()
                try:
                    ser.write(frame)
                    ser.flush()
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    print(f"  TX: [{timestamp}] {format_state(*decode(payload))}"
                          f"  (seq {seq}, {frame.hex(' ')})")
                except (serial.SerialException, OSError) as e:
                    print(f"  ERROR (transmitter): {e}")
                    mgr.reconnect(ser.port if ser else None)
                    # keep this frame for retry on the reconnected port
                    ser = mgr.get()
                    try:
                        ser.write(frame)
                        ser.flush()
                    except Exception as e2:
                        print(f"  ERROR (transmitter retry failed): {e2}")
                time.sleep(TX_SPACING)
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
    print(f"  Frame        : {FRAME_SIZE} bytes  (line format: id,px,py,pz,vx,vy,vz)")
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
