#!/usr/bin/env python3
"""Read-only RTX Spark runtime checks; missing optional channels are supported."""
import argparse
from pathlib import Path

POWER = {'sys_total', 'soc_pkg'}
ZONES = {'TSOC': 'soc', 'TS0E': 'cpu_e_clu0', 'TS0P': 'cpu_p_clu0',
         'TS1E': 'cpu_e_clu1', 'TS1P': 'cpu_p_clu1', 'TGPU': 'gpu',
         'TDLA': 'dla', 'TUNC': 'uncore'}
EXPECTED = POWER | set(ZONES.values())


def check(root, thermal=None, require_all=False):
    values = {}
    for p in root.glob('*_label'):
        label = p.read_text().strip()
        if label not in EXPECTED or label in values:
            raise ValueError(f'Unexpected or duplicate channel: {label}')
        kind = 'power' if label in POWER else 'temp'
        if not p.name.startswith(kind):
            raise ValueError(f'Wrong sensor class: {label}')
        value = int(p.with_name(p.name.replace('_label', '_input')).read_text())
        low, high = (0, 1000000000) if kind == 'power' else (-73150, 176850)
        if not low <= value <= high:
            raise ValueError(f'Out-of-range sensor: {label}={value}')
        values[label] = value
    if not values or (require_all and set(values) != EXPECTED):
        raise ValueError(f'Unexpected channel set: {set(values)}')
    if list(root.glob('power*_cap')):
        raise ValueError('RTX Spark backend must not expose power-limit writes')
    if thermal:
        for zone in thermal.glob('thermal_zone*'):
            label = ZONES.get((zone / 'type').read_text().strip())
            if label in values:
                # Sequential reads can differ while temperature changes.
                if abs(int((zone / 'temp').read_text()) - values[label]) > 5000:
                    raise ValueError(f'Temperature disagrees with thermal zone: {label}')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-all', action='store_true', help='require all ten known channels')
    args = parser.parse_args()
    roots = [p.parent for p in Path('/sys/class/hwmon').glob('hwmon*/name')
             if p.read_text().strip() == 'spbm_n1x']
    if len(roots) != 1:
        parser.exit(1, 'Expected one loaded spbm_n1x hwmon device\n')
    try:
        values = check(roots[0], Path('/sys/class/thermal'), args.require_all)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    print(f'PASS: {len(values)} plausible channels; temperatures agree; power controls absent')
    for label, value in values.items():
        print(f'{label}: {value}')


if __name__ == '__main__':
    main()
