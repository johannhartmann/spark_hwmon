#!/usr/bin/env python3
"""Read-only runtime checks for the H7607BA.300 backend; requires P16 hardware."""
from pathlib import Path

roots = [p.parent for p in Path('/sys/class/hwmon').glob('hwmon*/name')
         if p.read_text().strip() == 'spbm_n1x']
if len(roots) != 1:
    raise SystemExit('Expected one loaded spbm_n1x hwmon device')
root = roots[0]
expected = {'sys_total', 'soc_pkg', 'soc', 'cpu_e_clu0', 'cpu_p_clu0',
            'cpu_e_clu1', 'cpu_p_clu1', 'gpu', 'dla', 'uncore'}
values = {}
for p in root.glob('*_label'):
    label = p.read_text().strip()
    value = int(p.with_name(p.name.replace('_label', '_input')).read_text())
    values[label] = value
    low, high = (0, 1000000000) if p.name.startswith('power') else (-73150, 176850)
    if not low <= value <= high:
        raise SystemExit(f'Out-of-range sensor: {label}={value}')
if set(values) != expected:
    raise SystemExit(f'Unexpected channel set: {set(values)}')
if list(root.glob('power*_cap')):
    raise SystemExit('P16 must not expose power-limit writes')
zones = {'TSOC': 'soc', 'TS0E': 'cpu_e_clu0', 'TS0P': 'cpu_p_clu0',
         'TS1E': 'cpu_e_clu1', 'TS1P': 'cpu_p_clu1', 'TGPU': 'gpu',
         'TDLA': 'dla', 'TUNC': 'uncore'}
for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
    label = zones.get((zone / 'type').read_text().strip())
    if label:
        # Sequential reads can differ as hardware temperature changes.
        if abs(int((zone / 'temp').read_text()) - values[label]) > 5000:
            raise SystemExit(f'Temperature disagrees with thermal zone: {label}')
print('PASS: ten plausible channels; temperatures agree; power controls absent')
for label, value in values.items():
    print(f'{label}: {value}')
