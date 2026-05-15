# XBee 3 DigiMesh — Configuration & Communication Reference

## Overview

The XB3-24DMST-J is a 2.4 GHz DigiMesh module by Digi International. DigiMesh is a peer-to-peer mesh networking protocol where every node is equal — there is no coordinator, no router hierarchy. Any node can transmit, receive, and relay messages. All nodes that share the same PAN ID and channel form one network and can communicate with each other automatically.

---

## AT Command Parameters

### Network Identity

| Parameter | AT Command | Description | Your Value |
|---|---|---|---|
| PAN ID | `ATID` | Personal Area Network ID. All nodes must match. Nodes on different PAN IDs are invisible to each other even on the same channel. Range: `0x0` – `0x7FFF` | `7856` |
| Channel | `ATCH` | RF channel within the 2.4 GHz ISM band. Must match across all nodes. Default is `C`. | `C` |

### Node Identity

| Parameter | AT Command | Description | Value per Node |
|---|---|---|---|
| Node Identifier | `ATNI` | Human-readable name string. No effect on routing — purely a label visible in network scans and logs. Max 20 characters. | `DRONE_1` / `DRONE_2` / `DRONE_3` |
| Serial High | `ATSH` | Upper 32 bits of the factory-assigned 64-bit hardware address. Read-only. Used internally by DigiMesh for addressing. | (unique per module) |
| Serial Low | `ATSL` | Lower 32 bits of the 64-bit hardware address. Combined with ATSH gives the full unique node address. Read-only. | (unique per module) |

### Communication Mode

| Parameter | AT Command | Value | Description |
|---|---|---|---|
| API Mode | `ATAP` | `0` | **Transparent mode** — raw bytes written to serial are transmitted directly over RF. Simple, no frame parsing. Your current mode. |
| | | `1` | **API mode** — structured frames include source address, RSSI, delivery status. Required if you need to know which node sent a message. |

### Broadcast Behaviour

| Parameter | AT Command | Description | Your Value |
|---|---|---|---|
| Broadcast Hops | `ATBH` | Maximum number of hops a broadcast message can travel. `0` = network maximum (messages propagate until every node receives them). Relevant when nodes are out of direct range and need relay. | `0` |

### RF Performance

| Parameter | AT Command | Description | Your Value |
|---|---|---|---|
| TX Power Level | `ATPL` | Transmit power. Range `0` (lowest) to `4` (highest, +8 dBm / ~6 mW). Higher power = longer range but more current draw and RF interference between nodes. | `4` |
| Last Hop RSSI | `ATDB` | Read-only. Signal strength of the last received packet in dBm. More negative = weaker. Useful for diagnosing link quality. Your reading: –23 dBm (excellent). | read-only |

### Serial Interface

| Parameter | AT Command | Code | Baud Rate |
|---|---|---|---|
| Baud Rate | `ATBD` | `0` | 1200 bps |
| | | `1` | 2400 bps |
| | | `2` | 4800 bps |
| | | `3` | **9600 bps** ← your current setting |
| | | `4` | 19200 bps |
| | | `5` | 38400 bps |
| | | `6` | 57600 bps |
| | | `7` | 115200 bps |

### Firmware & Hardware

| Parameter | AT Command | Description |
|---|---|---|
| Firmware Version | `ATVR` | Current firmware version on the module. Your reading: `3012`. |
| Hardware Version | `ATHV` | Hardware revision. Your reading: `4246`. |

---

## Data Transmission

### RF Specs (XB3-24DMST-J)

| Property | Value |
|---|---|
| Frequency band | 2.400 – 2.484 GHz (2.4 GHz ISM) |
| RF data rate | 250 kbps (raw over-the-air) |
| Max TX power | +8 dBm (~6 mW) |
| Receive sensitivity | –96 dBm |
| Indoor range | up to ~60 m |
| Outdoor range (line of sight) | up to ~1500 m |
| Antenna interface | U.FL connector |
| Logic voltage | 3.3 V |

### Effective Throughput vs Raw RF Rate

The 250 kbps is the raw RF symbol rate. Actual usable throughput is lower due to:

- Protocol overhead (DigiMesh frame headers, addressing, checksums)
- ACK handshaking in unicast mode
- RF collisions in a busy mesh
- UART bottleneck at your current 9600 bps serial speed

| Bottleneck | Effective rate |
|---|---|
| UART at 9600 bps | ~960 bytes/sec |
| UART at 115200 bps | ~11,520 bytes/sec |
| RF (transparent mode, ideal) | ~20–30 kbps usable |

> At 9600 bps your UART is the limiting factor, not the RF link. If you need higher throughput, switch to `ATBD 7` (115200 bps) and reopen the serial port at the new baud.

### Broadcast vs Unicast

| Mode | How | Throughput | Address needed |
|---|---|---|---|
| Broadcast | `ATDL FFFF` | Lower — no ACK, all nodes receive | No |
| Unicast | `ATDL` = destination `ATSL` | Higher — ACK per packet, reliable delivery | Yes (ATSH + ATSL of target) |

In transparent mode with no `ATDL` set, the module uses its last configured destination. Set `ATDL FFFF` for broadcast to all nodes.

---

## RSSI Signal Strength Guide

| RSSI (dBm) | Link Quality |
|---|---|
| –10 to –40 | Excellent — nodes very close |
| –40 to –60 | Good — reliable communication |
| –60 to –75 | Usable — occasional retransmits |
| –75 to –90 | Weak — packet loss likely |
| Below –90 | Unreliable — near noise floor |

Your current reading of **–23 dBm** is excellent.

---

## Your 3-Node Mesh Configuration Summary

| | DRONE_1 | DRONE_2 | DRONE_3 |
|---|---|---|---|
| Port | `/dev/ttyUSB0` | `/dev/ttyUSB1` | `/dev/ttyUSB2` |
| `ATNI` | `DRONE_1` | `DRONE_2` | `DRONE_3` |
| `ATID` | `7856` | `7856` | `7856` |
| `ATCH` | `C` | `C` | `C` |
| `ATAP` | `0` | `0` | `0` |
| `ATBH` | `0` | `0` | `0` |
| `ATBD` | `3` (9600) | `3` (9600) | `3` (9600) |

---

## Communication Flow

```
DRONE_1 writes to send.txt
    └── comm.py reads send.txt
        └── ser.write() → UART → XBee (DRONE_1)
            └── RF broadcast (2.4 GHz, PAN ID 7856)
                ├── XBee (DRONE_2) → UART → comm.py → appended to receive.txt
                └── XBee (DRONE_3) → UART → comm.py → appended to receive.txt
```

---

## Key Commands Reference

```bash
# Enter command mode (no newline, wait 1 second either side)
+++

# Read a parameter
ATNI

# Write a parameter
ATNI DRONE_1

# Save to flash (always run after making changes)
ATWR

# Exit command mode
ATCN

# Reset module
ATFR
```

---

## File Reference

```
comm.py              Main bidirectional communication script
read_device.py       Read and display parameters from a connected XBee
tx_d1.txt            Send file for DRONE_1 — write messages here to transmit
tx_d2.txt            Send file for DRONE_2
tx_d3.txt            Send file for DRONE_3
rx_d1.txt            Received messages log for DRONE_1
rx_d2.txt            Received messages log for DRONE_2
rx_d3.txt            Received messages log for DRONE_3
test_transmit.py     Transmit test script
test_receive.py      Receive test script
guidevideo.mp4       Video walkthrough — setup, configuration, and running the mesh
README.md            This file
```

### Video Guide

<video width="100%" controls>
  <source src="./guidevideo.mp4" type="video/mp4">
</video>

- Connecting the XBee USB adapters to the Raspberry Pi
- Verifying devices on `/dev/ttyUSB*`
- Reading and verifying parameters with `read_device.py`
- Starting `comm.py` on all three nodes
- Sending a message and confirming it arrives on the other nodes
- Checking `rx_*.txt` log files

---

## User Guide

### Requirements

```bash
pip install pyserial
```

Connect each XBee USB adapter to the Raspberry Pi. Confirm ports are visible:

```bash
ls /dev/ttyUSB*
# Expected: /dev/ttyUSB0  /dev/ttyUSB1  /dev/ttyUSB2
```

---

### Step 1 — Read Current Device Parameters

Before doing anything, check what is currently configured on each device:

```bash
python3 read_device.py /dev/ttyUSB0
python3 read_device.py /dev/ttyUSB1
python3 read_device.py /dev/ttyUSB2
```

This prints all AT parameters (PAN ID, channel, node name, baud rate, RSSI etc.) for each device. Verify that `ATID` and `ATCH` match across all three before proceeding.

---

### Step 2 — Start Communication on Each Node

Open three terminals on your Raspberry Pi (or three SSH sessions). Run one `comm.py` instance per node:

```bash
# Terminal 1 — DRONE_1
python3 comm.py /dev/ttyUSB0 rx_d1.txt tx_d1.txt

# Terminal 2 — DRONE_2
python3 comm.py /dev/ttyUSB1 rx_d2.txt tx_d2.txt

# Terminal 3 — DRONE_3
python3 comm.py /dev/ttyUSB2 rx_d3.txt tx_d3.txt
```

Each instance opens the port for both sending and receiving simultaneously. Files are created automatically if they do not exist.

---

### Step 3 — Send a Message

To send a message from DRONE_1, write to its send file:

```bash
echo "Hello from DRONE_1" > tx_d1.txt
```

`comm.py` detects the new content within 0.5 seconds, transmits it over RF, and clears `tx_d1.txt` automatically. The message appears in `rx_d2.txt` and `rx_d3.txt` on the other nodes.

You can send multiple lines at once:

```bash
printf "line one\nline two\nline three\n" > tx_d1.txt
```

---

### Step 4 — Read Received Messages

Received messages are appended to the rx file with a timestamp:

```bash
cat rx_d2.txt
# [2026-05-15 10:32:01] Hello from DRONE_1
# [2026-05-15 10:32:05] line one
# [2026-05-15 10:32:05] line two
```

To watch messages arrive in real time:

```bash
tail -f rx_d2.txt
```

---

### Step 5 — Stop

Press `Ctrl+C` in any terminal to stop that node's `comm.py`. The serial port closes cleanly. The rx log file is preserved; the tx file is left as-is (empty if last transmission succeeded).

---

### Running Tests

To verify a single transmit/receive pair before running all three nodes:

```bash
# Terminal 1 — listen on USB1
python3 test_receive.py /dev/ttyUSB1

# Terminal 2 — send from USB0
python3 test_transmit.py /dev/ttyUSB0
```

---

### Typical Workflow Summary

```
1. python3 read_device.py /dev/ttyUSB*                        # verify all devices configured
2. python3 comm.py /dev/ttyUSB0 rx_d1.txt tx_d1.txt          # start node 1
   python3 comm.py /dev/ttyUSB1 rx_d2.txt tx_d2.txt          # start node 2
   python3 comm.py /dev/ttyUSB2 rx_d3.txt tx_d3.txt          # start node 3
3. echo "message" > tx_d1.txt                                 # send from node 1
4. tail -f rx_d2.txt                                          # watch on node 2
```

---

### Testing Parallel Send and Receive

This test fires a message from all three nodes simultaneously and confirms every node receives from the other two.

**Step 1 — Start all three nodes** (three terminals):

```bash
# Terminal 1
python3 comm.py /dev/ttyUSB0 SDU-Swarm-Comm-2/rx_d1.txt SDU-Swarm-Comm-2/tx_d1.txt

# Terminal 2
python3 comm.py /dev/ttyUSB1 SDU-Swarm-Comm-2/rx_d2.txt SDU-Swarm-Comm-2/tx_d2.txt

# Terminal 3
python3 comm.py /dev/ttyUSB2 SDU-Swarm-Comm-2/rx_d3.txt SDU-Swarm-Comm-2/tx_d3.txt
```

**Step 2 — Watch all rx files in real time** (fourth terminal):

```bash
tail -f SDU-Swarm-Comm-2/rx_d1.txt \
        SDU-Swarm-Comm-2/rx_d2.txt \
        SDU-Swarm-Comm-2/rx_d3.txt
```

**Step 3 — Trigger all three nodes to transmit at once** (fifth terminal):

```bash
echo "1 tx msg" >> SDU-Swarm-Comm-2/tx_d1.txt && \
echo "2 tx msg" >> SDU-Swarm-Comm-2/tx_d2.txt && \
echo "3 tx msg" >> SDU-Swarm-Comm-2/tx_d3.txt
```

**Expected result** — within 1–2 seconds each rx file should show messages from the other two nodes:

```
# rx_d1.txt  (DRONE_1 receives from D2 and D3)
[2026-05-15 10:45:01] 2 tx msg
[2026-05-15 10:45:01] 3 tx msg

# rx_d2.txt  (DRONE_2 receives from D1 and D3)
[2026-05-15 10:45:01] 1 tx msg
[2026-05-15 10:45:01] 3 tx msg

# rx_d3.txt  (DRONE_3 receives from D1 and D2)
[2026-05-15 10:45:01] 1 tx msg
[2026-05-15 10:45:01] 2 tx msg
```

> Note: in transparent mode all three nodes transmit at nearly the same instant, which can cause RF collisions. If a message is missing from an rx file, re-run the Step 3 command — occasional collisions are normal. For reliable simultaneous transmission, stagger the sends by a small offset (50–100 ms per node) or switch to API mode with TDMA slot scheduling.

---

### Troubleshooting

**Port not found (`/dev/ttyUSB*` missing)**
Check USB connections and run `dmesg | tail -20` to see if the adapter was detected.

**`comm.py` fails to open port**
Another process may be holding the port. Check with `lsof /dev/ttyUSB0` and kill it if needed.

**Messages not received on other nodes**
Run `read_device.py` on all devices and confirm `ATID` and `ATCH` match. Also confirm `ATAP` is `0` (transparent mode) on all nodes.

**Garbled output in rx file**
Baud rate mismatch. Confirm `ATBD` is the same on all devices and matches the baud rate in `comm.py` (default 9600).

**TX file not clearing**
A serial error occurred mid-transmission. Check the terminal running `comm.py` for the error message. The file is intentionally kept so the message can be retried.
