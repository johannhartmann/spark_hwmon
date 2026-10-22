#!/usr/bin/env python3
"""Bounded power-limit reductions for P16 H7607BA BIOS .300; always restore.

Fixed address/slot/value, guarded initial state, temperature abort and independent
watchdog. Research tool: run pinned CPU workload separately as the normal user.
"""
import argparse
import fcntl
import json
import mmap
import os
from pathlib import Path
import signal
import struct
import time

BASE = 0x1c238000
OFFSETS = (0, 8, 0x38, 0x48, 0x4c) + tuple(range(0x100, 0x180, 4)) + (
    0x300, 0x304, 0x30c, 0x310, 0x324, 0x380, 0x384, 0x388, 0x38c,
    0x708, 0x70c, 0x800, 0x804, 0x80c, 0x810, 0x814, 0x818, 0x81c,
    0x820, 0x824, 0x828, 0x82c, 0x830, 0x834, 0x838) + tuple(range(0x200, 0x280, 4)) + tuple(range(0x620, 0x638, 4))


def experiment(output, case="pl1", long_window=False):
    end_time, restore_time = (105, 92) if long_window else (45, 32)
    cases = {"pl1": {0: 35000}, "package": {0: 35000, 1: 40000},
             "system": {4: 75000, 5: 85000}, "sustained-system": {4: 60000}}
    overrides = cases[case]
    for key, expected in [('sys_vendor', 'ASUS'), ('product_name', 'ProArt P16 H7607BA'),
                          ('bios_version', 'H7607BA.300')]:
        if Path('/sys/class/dmi/id', key).read_text().strip() != expected:
            raise ValueError(f'Unsupported platform: {key}')
    if os.geteuid() != 0:
        raise ValueError('Root is required')
    lock_fd = os.open('/run/lock/spark-hwmon-n1x-cap.lock',
                      os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'w') as lock, output.open('x') as stream:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        try:
            with mmap.mmap(fd, mmap.PAGESIZE, flags=mmap.MAP_SHARED,
                           prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=BASE) as memory:
                def read(offset):
                    return struct.unpack_from('<I', memory, offset)[0]
                def write_override(enabled):
                    for slot, target in overrides.items():
                        for i, byte in enumerate(struct.pack('<I', target if enabled else 0)):
                            memory[0x100 + slot * 4 + i] = byte
                    struct.pack_into('<I', memory, 0, 1)
                if any(read(o) for o in range(0x100, 0x120, 4)):
                    raise ValueError('An OS override is already active')
                for slot, target in overrides.items():
                    domain = slot if slot < 4 else slot - 1
                    low, high = read(0x708 + domain * 16), read(0x70c + domain * 16)
                    default = read(0x120 + slot * 4)
                    if not low <= target < default <= high or read(0x160 + slot * 4) != default:
                        raise ValueError('Unexpected bounds/default/effective limit')
                if any(not 2000 < read(o) < 3600 for o in (0x818, 0x830)):
                    raise ValueError('Unexpected or excessive initial temperature')
                stream.write(json.dumps({'kind': 'metadata', 'physical_base': BASE,
                    'original_limits_mw': {str(slot): read(0x160 + slot * 4) for slot in overrides},
                    'bios': 'H7607BA.300', 'case': case, 'overrides_mw': overrides, 'restore_time_s': restore_time, 'end_time_s': end_time}) + '\n'); stream.flush()
                read_pipe, write_pipe = os.pipe()
                watchdog = os.fork()
                if watchdog == 0:
                    os.close(write_pipe)
                    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                        signal.signal(sig, signal.SIG_IGN)
                    import select
                    select.select([read_pipe], [], [], end_time + 10)
                    write_override(False)
                    os._exit(0)
                os.close(read_pipe)
                def interrupted(signum, frame):
                    raise InterruptedError(f'Signal {signum}')
                old = {sig: signal.signal(sig, interrupted)
                       for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
                start = time.monotonic(); applied = restored = False
                try:
                    print('Bounded cap experiment ready', flush=True)
                    while time.monotonic() - start < end_time:
                        now = time.monotonic(); elapsed = now - start
                        if elapsed >= 12 and not applied:
                            write_override(True); applied = True
                            print(f'Overrides applied: {overrides}', flush=True)
                        if elapsed >= restore_time and not restored:
                            write_override(False); restored = True
                            print('Overrides restored to zero', flush=True)
                        phase = 'baseline' if not applied else ('restored' if restored else 'limited')
                        row = {'kind': 'sample', 'monotonic_s': now, 'elapsed_s': elapsed,
                               'phase': phase, 'registers': {f'0x{o:03x}': read(o) for o in OFFSETS}}
                        row['cpu_frequency_khz'] = {p.parent.name: int(p.read_text()) for p in
                            Path('/sys/devices/system/cpu/cpufreq').glob('policy*/scaling_cur_freq')}
                        stream.write(json.dumps(row) + '\n'); stream.flush()
                        if any(not 2000 < read(o) < 3600 for o in (0x818, 0x830)):
                            raise RuntimeError('Temperature guard tripped')
                        if applied and not restored and elapsed > 14 and any(read(0x100 + slot * 4) != target for slot, target in overrides.items()):
                            raise RuntimeError('Override readback failed')
                        time.sleep(.1)
                finally:
                    write_override(False)
                    os.close(write_pipe); os.waitpid(watchdog, 0)
                    time.sleep(.3)
                    state = {'kind': 'restoration', 'override_mw': read(0x100),
                             'effective_mw': read(0x160), 'ec_mw': read(0x120)}
                    if case != 'pl1':
                        state['slots'] = {str(slot): {'override_mw': read(0x100 + slot * 4),
                            'effective_mw': read(0x160 + slot * 4), 'ec_mw': read(0x120 + slot * 4)} for slot in overrides}
                    stream.write(json.dumps(state) + '\n'); stream.flush()
                    for sig, handler in old.items(): signal.signal(sig, handler)
                    print(json.dumps(state), flush=True)
                    if any(read(0x100 + slot * 4) != 0 or read(0x160 + slot * 4) != read(0x120 + slot * 4) for slot in overrides):
                        raise RuntimeError('Effective limit did not restore to the EC value')
        finally:
            os.close(fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--case', choices=('pl1', 'package', 'system', 'sustained-system'), default='pl1')
    parser.add_argument('--long-window', action='store_true', help='80-second limited phase for SysPL1 settling')
    args = parser.parse_args()
    experiment(args.output, args.case, args.long_window)
