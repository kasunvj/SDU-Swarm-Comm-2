#!/usr/bin/env python3

import sys
import time
from datetime import datetime

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <filename> <delay_ms>")
    sys.exit(1)

filename = sys.argv[1]
delay_ms = int(sys.argv[2])

count = 1

while True:
    current_time = datetime.now().isoformat(timespec='microseconds')
    msg = f"{current_time} msg: {count} D1 Pos X:123.4,Y:300,Z:400"

    with open(filename, "w") as f:
        f.write(msg + "\n")

    count += 1
    time.sleep(delay_ms / 1000.0)