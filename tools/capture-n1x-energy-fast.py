#!/usr/bin/env python3
"""Read eight energy/power words every millisecond for 20 seconds, P16 .300 only.

No workload or hardware writes. This measures the producer's update cadence;
faster polling does not imply finer firmware sampling or calibrated energy.
"""
import argparse
import json
import mmap
import os
from pathlib import Path
import struct
import time

BASE = 0x1c238000
OFFSETS = (0x304, 0x30c, 0x310, 0x324, 0x344, 0x350, 0x35c, 0x374)


def capture(output):
    for key, expected in [('sys_vendor', 'ASUS'), ('product_name', 'ProArt P16 H7607BA'),
                          ('bios_version', 'H7607BA.300')]:
        if Path('/sys/class/dmi/id', key).read_text().strip() != expected:
            raise ValueError(f'Unsupported platform: {key}')
    with output.open('x') as stream:
        fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
        try:
            with mmap.mmap(fd, mmap.PAGESIZE, flags=mmap.MAP_SHARED,
                           prot=mmap.PROT_READ, offset=BASE) as memory:
                stream.write(json.dumps({'kind': 'metadata', 'interval_s': .001,
                    'bios': 'H7607BA.300', 'offsets': OFFSETS}) + '\n')
                stream.flush()
                start = time.monotonic()
                sequence = 0
                while time.monotonic() - start < 20:
                    now = time.monotonic()
                    values = {f'0x{o:03x}': struct.unpack_from('<I', memory, o)[0] for o in OFFSETS}
                    stream.write(json.dumps({'kind': 'sample', 'monotonic_s': now,
                        'elapsed_s': now - start, 'phase': 'idle', 'registers': values}) + '\n')
                    sequence += 1
                    if sequence % 100 == 0:
                        stream.flush()
                    time.sleep(max(0, start + sequence * .001 - time.monotonic()))
        finally:
            os.close(fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    capture(parser.parse_args().output)
