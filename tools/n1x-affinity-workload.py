#!/usr/bin/env python3
"""Exercise MIDR-identified E/P cores separately alongside read-only capture.

Run as the ordinary user. Children set and verify single-core affinity before
hashing, and report their actual affinity. No CPU governor or profile is changed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def topology():
    groups = {'e': [], 'p': []}
    for cpu in sorted(os.sched_getaffinity(0)):
        path = Path(f'/sys/devices/system/cpu/cpu{cpu}/regs/identification/midr_el1')
        midr = int(path.read_text().strip(), 16)
        if midr >> 24 != 0x41:
            raise ValueError(f'Unrecognized implementer on CPU {cpu}')
        part = (midr >> 4) & 0xfff
        # Arm MIDR: Cortex-A725 0xd87, Cortex-X925 0xd85.
        if part not in (0xd87, 0xd85):
            raise ValueError(f'Unrecognized CPU {cpu}: {midr:#x}')
        groups['e' if part == 0xd87 else 'p'].append(cpu)
    if any(len(cpus) != 10 for cpus in groups.values()):
        raise ValueError(f'Expected ten E and ten P cores, got {groups}')
    return groups


def run(capture, phase_file, events_file):
    if os.geteuid() == 0:
        raise ValueError('Run workloads as the ordinary user')
    groups = topology()
    with events_file.open('x') as output:
        record = {'topology': groups, 'events': [], 'workers': []}
        children = []
        try:
            deadline = time.monotonic() + 90
            while not capture.exists() or capture.stat().st_size < 20:
                if time.monotonic() > deadline:
                    raise TimeoutError('Capture did not start')
                time.sleep(.2)
            if time.time() - capture.stat().st_mtime > 5:
                raise ValueError('Capture is stale')
            worker = ('import hashlib,json,os,sys,time; c=int(sys.argv[1]); '
                      'os.sched_setaffinity(0,{c}); '
                      'assert os.sched_getaffinity(0)=={c}; '
                      'print(json.dumps({"cpu":c,"affinity":list(os.sched_getaffinity(0))}),flush=True); '
                      'd=b"x"*131072; end=time.monotonic()+20;\n'
                      'while time.monotonic()<end: hashlib.sha256(d).digest()')
            for phase, seconds in [('idle', 12), ('e', 20), ('recovery_e', 12),
                                   ('p', 20), ('recovery_p', 12), ('e_repeat', 20),
                                   ('cooldown', 8)]:
                phase_file.write_text(phase)
                record['events'].append({'phase': phase, 'monotonic': time.monotonic()})
                print(phase, flush=True)
                cpus = groups['e' if phase.startswith('e') else 'p'] if phase in ('e', 'p', 'e_repeat') else []
                children = [subprocess.Popen([sys.executable, '-c', worker, str(cpu)],
                                             stdout=subprocess.PIPE, text=True) for cpu in cpus]
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    for name in Path('/sys/class/hwmon').glob('hwmon*/name'):
                        if name.read_text().strip() == 'spbm_n1x':
                            for sensor in name.parent.glob('temp*_input'):
                                if int(sensor.read_text()) > 90000:
                                    raise RuntimeError('Temperature exceeded 90 C')
                    time.sleep(.25)
                for child in children:
                    stdout, _ = child.communicate(timeout=5)
                    if child.returncode:
                        raise RuntimeError('Affinity worker failed')
                    record['workers'].append({'phase': phase, **json.loads(stdout)})
                children = []
        except BaseException as error:
            record['error'] = str(error)
            raise
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                child.communicate(timeout=5)
            json.dump(record, output, indent=2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('phase_file', type=Path)
    parser.add_argument('events_file', type=Path)
    args = parser.parse_args()
    run(args.capture, args.phase_file, args.events_file)
