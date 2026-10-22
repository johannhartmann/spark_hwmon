#!/usr/bin/env python3
"""Read-only RTX Spark runtime checks; missing optional channels are supported."""
import argparse
from pathlib import Path

POWER = {'sys_total', 'soc_pkg'}
ZONES = {'TSOC': 'soc', 'TS0E': 'cpu_e_clu0', 'TS0P': 'cpu_p_clu0',
         'TS1E': 'cpu_e_clu1', 'TS1P': 'cpu_p_clu1', 'TGPU': 'gpu',
         'TDLA': 'dla', 'TUNC': 'uncore'}
EXPECTED = POWER | set(ZONES.values())
MMIO_POWER = {'sys_instant', 'pkg_instant', 'cpu_gpu', 'cpu_p', 'cpu_e',
              'vcore', 'gpu', 'prereg', 'dc_input', 'pl1', 'pl2', 'syspl1', 'syspl2'}
LIMITS = {'pl1', 'pl2', 'syspl1', 'syspl2'}


def check(root, thermal=None, require_all=False, require_mmio=False):
    values, seen, channels = {}, set(), {}
    mmio = (root / 'prochot_raw').exists()
    for p in root.glob('*_label'):
        label = p.read_text().strip()
        kind = 'power' if p.name.startswith('power') else 'temp' if p.name.startswith('temp') else ''
        allowed = (POWER | (MMIO_POWER if mmio else set())) if kind == 'power' else set(ZONES.values())
        if not kind or label not in allowed or (kind, label) in seen:
            raise ValueError(f'Unexpected, duplicate or wrong sensor class: {label}')
        seen.add((kind, label))
        stem = p.name.removesuffix('_label')
        channels[stem] = label
        value = int((root / f'{stem}_input').read_text())
        low, high = (0, 1000000000) if kind == 'power' else (-73150, 176850)
        if not low <= value <= high:
            raise ValueError(f'Out-of-range sensor: {label}={value}')
        key = f'power:{label}' if kind == 'power' and label not in POWER else label
        values[key] = value
    if not values or (require_all and not EXPECTED <= set(values)):
        raise ValueError(f'Unexpected channel set: {set(values)}')
    for cap in root.glob('power*_cap'):
        stem = cap.name.removesuffix('_cap')
        if not mmio or channels.get(stem) not in LIMITS:
            raise ValueError('Unvalidated power control exposed')
        low = int((root / f'{stem}_min').read_text())
        high = int((root / f'{stem}_max').read_text())
        if not 0 < low <= high <= 250000000 or not 0 < int(cap.read_text()) <= 250000000:
            raise ValueError(f'Invalid power limit contract: {stem}')
    if require_mmio:
        if not mmio or not {f'power:{label}' for label in MMIO_POWER} <= set(values):
            raise ValueError('Missing validated MMIO power channels')
        if len(list(root.glob('power*_cap'))) != 4:
            raise ValueError('Expected four validated power controls')
        for name in ('pl_level_raw', 'prochot_raw', 'control_038_raw',
                     'diagnostic_380_raw', 'diagnostic_384_raw', 'diagnostic_388_raw',
                     'diagnostic_38c_raw'):
            if not 0 <= int((root / name).read_text()) <= 0xffffffff:
                raise ValueError(f'Invalid raw register: {name}')
        for domain in ('pkg', 'cpu_e', 'cpu_p', 'gpc', 'gpu'):
            for suffix in ('raw', 'overflow_raw', 'clear_raw'):
                name = f'{domain}_energy_{suffix}'
                if not 0 <= int((root / name).read_text()) <= 0xffffffff:
                    raise ValueError(f'Invalid raw energy word: {name}')
        if list(root.glob('energy*_input')):
            raise ValueError('Uncalibrated energy must remain raw')
    if thermal:
        for zone in thermal.glob('thermal_zone*'):
            label = ZONES.get((zone / 'type').read_text().strip())
            if label in values:
                if abs(int((zone / 'temp').read_text()) - values[label]) > 5000:
                    raise ValueError(f'Temperature disagrees with thermal zone: {label}')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-all', action='store_true', help='require all ten known channels')
    parser.add_argument('--require-mmio', action='store_true', help='require the validated P16 MMIO extension')
    args = parser.parse_args()
    roots = [p.parent for p in Path('/sys/class/hwmon').glob('hwmon*/name')
             if p.read_text().strip() == 'spbm_n1x']
    if len(roots) != 1:
        parser.exit(1, 'Expected one loaded spbm_n1x hwmon device\n')
    try:
        values = check(roots[0], Path('/sys/class/thermal'), args.require_all, args.require_mmio)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
    print(f'PASS: {len(values)} plausible channels; temperatures agree; control exposure validated')
    for label, value in values.items():
        print(f'{label}: {value}')


if __name__ == '__main__':
    main()
