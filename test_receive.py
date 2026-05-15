import serial
ser = serial.Serial('/dev/ttyUSB1', 9600, timeout=None)
print('Listening on USB1...')
while True:
    line = ser.readline().decode(errors='ignore').strip()
    if line:
        print(f'RX: {line}')