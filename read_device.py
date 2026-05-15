import serial
import time
import sys

PORTS    = ['/dev/ttyUSB0']
BAUDRATE = 9600

COMMANDS = {
    'ATNI': 'Node Identifier',
    'ATID': 'PAN ID',
    'ATCH': 'Channel',
    'ATAP': 'API Mode',
    'ATVR': 'Firmware Version',
    'ATHV': 'Hardware Version',
    'ATBD': 'Baud Rate',
    'ATMY': 'Module Address',
    'ATSH': 'Serial High',
    'ATSL': 'Serial Low',
    'ATBH': 'Broadcast Hops',
    'ATPL': 'TX Power Level',
    'ATDB': 'Last Hop RSSI',
}
 
BAUD_MAP = {
    '0': '1200',   '1': '2400',   '2': '4800',
    '3': '9600',   '4': '19200',  '5': '38400',
    '6': '57600',  '7': '115200',
}

AP_MAP = {
    '0': 'Transparent',
    '1': 'API Mode',
    '2': 'API Mode (escaped)',
}

def send_cmd(ser, cmd):
    ser.write((cmd + '\r').encode())
    time.sleep(0.15)
    return ser.read(100).decode(errors='ignore').strip()

def decode_value(cmd, raw):
    if cmd == 'ATBD':
        return f"{raw}  ({BAUD_MAP.get(raw, '?')} bps)"
    if cmd == 'ATAP':
        return f"{raw}  ({AP_MAP.get(raw, '?')})"
    if cmd == 'ATDB':
        try:
            return f"-{int(raw, 16)} dBm"
        except ValueError:
            return raw
    return raw

def print_separator(char='─', width=55):
    print(char * width)

def read_xbee(port):
    print_separator()
    print(f"  Device : {port}")
    print_separator()

    try:
        ser = serial.Serial(port, BAUDRATE, timeout=1)
    except serial.SerialException as e:
        print(f"  ERROR  : Cannot open port — {e}")
        print()
        return

    try:
        # Enter command mode
        time.sleep(1)
        ser.write(b'+++')
        time.sleep(1.2)
        resp = ser.read(10).decode(errors='ignore')

        if 'OK' not in resp:
            print(f"  ERROR  : Did not enter command mode (got: {repr(resp)})")
            print(f"           Check baud rate or device connection")
            print()
            ser.close()
            return

        print(f"  Status : Command mode OK\n")

        # Read each parameter
        for cmd, label in COMMANDS.items():
            raw = send_cmd(ser, cmd)
            val = decode_value(cmd, raw)
            print(f"  {cmd}  {label:<22} {val}")

        # Exit command mode
        send_cmd(ser, 'ATCN')
        print()

    except serial.SerialException as e:
        print(f"  ERROR  : Serial error — {e}\n")

    finally:
        ser.close()

def main():
    print()
    print("  XBee DigiMesh Parameter Reader")
    print(f"  Scanning {len(PORTS)} devices at {BAUDRATE} baud")
    print()
 
    # Allow custom ports as CLI args: python3 xbee_reader.py /dev/ttyUSB0 /dev/ttyUSB1
    ports = sys.argv[1:] if len(sys.argv) > 1 else PORTS
 
    for port in ports:
        read_xbee(port)
 
    print_separator('═')
    print("  Done")
    print_separator('═')
    print()
 
if __name__ == '__main__':
    main()