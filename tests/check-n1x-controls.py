#!/usr/bin/env python3
"""Validate four sysfs cap writes with 1 W reductions, restoring each immediately."""
import fcntl
import json
import os
from pathlib import Path
import time


def wait_value(path, expected):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if int(path.read_text()) == expected:
            return
        time.sleep(.05)
    raise RuntimeError(f'{path.name} did not become {expected}')


def main():
    for key, value in [('sys_vendor', 'ASUS'), ('product_name', 'ProArt P16 H7607BA'),
                       ('bios_version', 'H7607BA.300')]:
        if Path('/sys/class/dmi/id', key).read_text().strip() != value:
            raise RuntimeError('Unvalidated firmware')
    if os.geteuid() != 0:
        raise RuntimeError('Run as root')
    roots = [p.parent for p in Path('/sys/class/hwmon').glob('hwmon*/name')
             if p.read_text().strip() == 'spbm_n1x']
    if len(roots) != 1:
        raise RuntimeError('Expected one spbm_n1x device')
    root = roots[0]
    if any(int(p.read_text()) > 85000 for p in root.glob('temp*_input')):
        raise RuntimeError('Temperature too high for control validation')
    flags = os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW
    with os.fdopen(os.open('/run/lock/spark-hwmon-n1x-cap.lock', flags, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        labels = {p.read_text().strip(): p.name.removesuffix('_label')
                  for p in root.glob('power*_label')}
        limits = ('pl1', 'pl2', 'syspl1', 'syspl2')
        if any(int((root / f'{label}_request_raw').read_text()) for label in limits):
            raise RuntimeError('Existing overrides must be left untouched')
        results = []
        for label in limits:
            stem = labels[label]
            cap, request = root / f'{stem}_cap', root / f'{label}_request_raw'
            before = int(cap.read_text())
            target = min(before, int((root / f'{stem}_max').read_text())) - 1000000
            if target < int((root / f'{stem}_min').read_text()):
                raise RuntimeError('Insufficient range for a 1 W reduction')
            try:
                cap.write_text(str(target))
                wait_value(request, target // 1000)
                wait_value(cap, target)
                results.append({'limit': label, 'before_uw': before, 'requested_uw': target,
                                'effective_uw': int(cap.read_text())})
            finally:
                # Preserve any external writer's replacement request.
                if int(request.read_text()) == target // 1000:
                    cap.write_text('0')
                wait_value(request, 0)
            wait_value(cap, int((root / f'{stem}_max').read_text()))
            results[-1]['restored_uw'] = int(cap.read_text())
        print(json.dumps({'module_version': Path('/sys/module/spbm/version').read_text().strip(),
                          'controls': results, 'all_requests_zero': True}, indent=2))


if __name__ == '__main__':
    main()
