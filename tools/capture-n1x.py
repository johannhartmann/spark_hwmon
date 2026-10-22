#!/usr/bin/env python3
"""Read-only, bounded N1X register capture for the validated P16 BIOS only.

No commands, limits, profiles or module state are changed. /dev/mem is opened
read-only and mapped PROT_READ. All physical addresses are fixed here; arbitrary
addresses cannot be supplied. Output is JSONL, created exclusively.
"""
import argparse
import datetime
import json
import mmap
import os
from pathlib import Path
import platform
import struct
import time

BASE = 0x1c238000
VENDOR_OFFSETS = tuple(range(0x100, 0x180, 4)) + (
    0x800, 0x80c, 0x804, 0x810, 0x38, 0x808, 0x814, 0x30c,
    0x310, 0x324, 0x38c, 0x344, 0x380, 0x35c, 0x350, 0x374,
)
# Legacy DGX power telemetry window (upstream commit 94b5972). These are
# additional N1X candidates, not asserted sensor identities or units.
LEGACY_POWER_OFFSETS = tuple(range(0x300, 0x340, 4))
# Adjacent words of the four candidate energy records and timestamp record.
# Their interpretation is deliberately left raw; this does not assume u64 energy.
RECORD_WORDS = tuple(offset + step for offset in (0x344, 0x350, 0x35c, 0x374, 0x380)
                     for step in (4, 8))
# Firmware DSDT _TMP accessors independently establish these temperature addresses.
TEMP_OFFSETS = (0x818, 0x820, 0x824, 0x828, 0x82c, 0x830, 0x834, 0x838)
OFFSETS = sorted(set(VENDOR_OFFSETS + LEGACY_POWER_OFFSETS + RECORD_WORDS + TEMP_OFFSETS))


def read_text(path):
    return Path(path).read_text().strip()


def capture(output, duration, interval, phase_file=None):
    dmi = Path('/sys/class/dmi/id')
    product = read_text(dmi / 'product_name')
    bios = read_text(dmi / 'bios_version')
    vendor = read_text(dmi / 'sys_vendor')
    if vendor != 'ASUS' or product != 'ProArt P16 H7607BA' or bios != 'H7607BA.300':
        raise ValueError('Unvalidated platform: this capture is restricted to P16 H7607BA BIOS .300')
    if read_text('/sys/bus/acpi/devices/NVDA8810:00/path') != r'\_SB_.MTEL':
        raise ValueError('Expected NVDA8810 MTEL device is absent')
    if platform.machine() != 'aarch64' or BASE % mmap.PAGESIZE:
        raise ValueError('Unsupported architecture or page alignment')
    references = []
    for hwmon in Path('/sys/class/hwmon').glob('hwmon*'):
        if read_text(hwmon / 'name') == 'spbm_n1x':
            for label in hwmon.glob('*_label'):
                references.append((label.with_name(label.name.replace('_label', '_input')),
                                   read_text(label)))
    metadata = {'kind': 'metadata', 'platform': product, 'bios': bios,
                'kernel': platform.release(), 'physical_base': BASE,
                'offsets': OFFSETS, 'interval_s': interval,
                'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'platform_profile': read_text('/sys/firmware/acpi/platform_profile'),
                'spbm_version': read_text('/sys/module/spbm/version')}
    # Create output first: a refused path must not cause any device access.
    with output.open('x') as stream:
        fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
        try:
            with mmap.mmap(fd, mmap.PAGESIZE, flags=mmap.MAP_SHARED,
                           prot=mmap.PROT_READ, offset=BASE) as memory:
                stream.write(json.dumps(metadata) + '\n')
                stream.flush()
                print('Read-only capture ready', flush=True)
                start = time.monotonic()
                sequence = 0
                while time.monotonic() - start < duration:
                    now = time.monotonic()
                    phase = 'unspecified'
                    if phase_file:
                        with phase_file.open() as phase_stream:
                            phase = phase_stream.read(80).strip()
                    values = {f'0x{offset:03x}': struct.unpack_from('<I', memory, offset)[0]
                              for offset in OFFSETS}
                    hwmon = {}
                    for path, label in references:
                        try:
                            hwmon[label] = int(read_text(path))
                        except (OSError, ValueError):
                            hwmon[label] = None
                    sample = {'kind': 'sample', 'monotonic_s': now,
                              'elapsed_s': now - start, 'phase': phase,
                              'registers': values, 'hwmon': hwmon}
                    stream.write(json.dumps(sample) + '\n')
                    stream.flush()
                    sequence += 1
                    time.sleep(max(0, start + sequence * interval - time.monotonic()))
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--duration', type=float, default=20)
    parser.add_argument('--interval', type=float, default=.1)
    parser.add_argument('--phase-file', type=Path)
    args = parser.parse_args()
    if not 0.1 <= args.duration <= 120 or not .05 <= args.interval <= 10:
        parser.error('duration must be 0.1..120 seconds; interval must be 0.05..10 seconds')
    try:
        capture(args.output, args.duration, args.interval, args.phase_file)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
