import serial, time
ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
i = 0
while True:
    msg = f'Hello from D1 #{i}\n'
    ser.write(msg.encode())
    print(f'TX: {msg.strip()}')
    i += 1
    time.sleep(1)