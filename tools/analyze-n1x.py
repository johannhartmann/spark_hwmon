#!/usr/bin/env python3
"""Summarize raw N1X capture phases and test candidate mJ/mW relationships.

A numerical match is evidence, not a register specification. In particular,
this does not establish counter width, reset behavior or writable controls.
"""
import argparse
import gzip
import itertools
import json
import math
from pathlib import Path
import statistics

PAIRS = (
    ('package_vs_acpi', '0x344', '0x800'),
    ('package_vs_804', '0x344', '0x804'),
    ('package_vs_legacy', '0x344', '0x304'),
    ('cpu_p', '0x35c', '0x30c'),
    ('cpu_e', '0x350', '0x310'),
    ('gpu', '0x374', '0x324'),
)


def summarize(records):
    if not records or records[0].get('kind') != 'metadata':
        raise ValueError('Missing capture metadata')
    samples = records[1:]
    if len(samples) < 2:
        raise ValueError('At least two samples are required')
    previous = -math.inf
    for row in samples:
        now = row.get('monotonic_s', math.nan)
        if row.get('kind') != 'sample' or not math.isfinite(now) or now <= previous:
            raise ValueError('Sample timestamps must be finite and strictly increasing')
        previous = now
        if any(type(value) is not int or not 0 <= value <= 0xffffffff
               for value in row['registers'].values()):
            raise ValueError('Registers must contain unsigned 32-bit integers')
    report = {'metadata': records[0], 'sample_count': len(samples), 'phases': []}
    # Preserve separate runs of a phase; never integrate through another workload.
    for phase, rows in itertools.groupby(samples, key=lambda row: row['phase']):
        rows = list(rows)
        duration = rows[-1]['monotonic_s'] - rows[0]['monotonic_s']
        keys = set.intersection(*(set(row['registers']) for row in rows))
        stats = {key: {'min': min(values), 'max': max(values),
                       'mean': statistics.mean(values)}
                 for key in sorted(keys)
                 for values in [[row['registers'][key] for row in rows]]}
        comparisons = {}
        for name, energy, power in PAIRS:
            if duration <= 0 or energy not in keys or power not in keys:
                continue
            # Each interval can contain at most one u32 rollover in this short
            # experiment. Summing per interval also exposes decreases separately.
            delta = sum((right['registers'][energy] - left['registers'][energy]) % 2**32
                        for left, right in zip(rows, rows[1:]))
            decreases = sum(right['registers'][energy] < left['registers'][energy]
                            for left, right in zip(rows, rows[1:]))
            integral = sum((right['monotonic_s'] - left['monotonic_s']) *
                           (left['registers'][power] + right['registers'][power]) / 2
                           for left, right in zip(rows, rows[1:]))
            comparisons[name] = {'candidate_energy_offset': energy,
                                 'candidate_power_offset': power,
                                 'counter_delta_mod_u32': delta,
                                 'counter_decreases': decreases,
                                 'power_time_integral_raw': integral,
                                 'ratio_if_mJ_and_mW': delta / integral if integral else None}
        report['phases'].append({'phase': phase, 'samples': len(rows),
                                 'duration_s': duration, 'registers': stats,
                                 'candidate_energy_checks': comparisons})
    return report


def load(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as stream:
        return [json.loads(line) for line in stream if line.strip()]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    args = parser.parse_args()
    try:
        result = summarize(load(args.capture))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2, allow_nan=False))
