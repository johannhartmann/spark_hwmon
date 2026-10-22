"""Verify bounded power-control and affinity experiment evidence offline."""
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import unittest

DATA = Path(__file__).resolve().parent.parent / 'docs/validation'


def load(name):
    return [json.loads(line) for line in gzip.decompress((DATA / (name + '.jsonl.gz')).read_bytes()).splitlines()]


class GapEvidenceTests(unittest.TestCase):
    def test_new_capture_hashes_and_record_counts(self):
        manifest = json.loads((DATA / 'manifest.json').read_text())
        for name in ('affinity-capture', 'cap-experiment', 'bounds-capture', 'status-capture',
                     'package-cap-experiment', 'system-cap-experiment',
                     'system-long-cap-experiment', 'sustained-system-cap-experiment', 'pid-capture',
                     'final-state-capture'):
            with self.subTest(name=name):
                data = (DATA / (name + '.jsonl.gz')).read_bytes()
                expected = manifest[name + '.jsonl.gz']
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected['sha256_gzip'])
                self.assertEqual(hashlib.sha256(gzip.decompress(data)).hexdigest(), expected['sha256_jsonl'])
                self.assertEqual(sum(r['kind'] == 'sample' for r in load(name)), expected['samples'])

    def test_pinned_e_load_selectively_excites_e_energy(self):
        rows = load('affinity-capture')[1:]
        events = json.loads((DATA / 'affinity-events.json').read_text())
        self.assertNotIn('error', events)
        self.assertEqual(len(events['topology']['e']), 10)
        self.assertEqual(len(events['topology']['p']), 10)
        self.assertFalse(set(events['topology']['e']) & set(events['topology']['p']))
        for worker in events['workers']:
            self.assertEqual(worker['affinity'], [worker['cpu']])
            self.assertIn(worker['cpu'], events['topology']['e' if worker['phase'].startswith('e') else 'p'])
        def rate(phase, key):
            group = [r for r in rows if r['phase'] == phase]
            elapsed = group[-1]['monotonic_s'] - group[0]['monotonic_s']
            return (group[-1]['registers'][key] - group[0]['registers'][key]) / elapsed
        for phase in ('e', 'e_repeat'):
            self.assertGreater(rate(phase, '0x350'), 6 * rate('recovery_e', '0x350'))
            self.assertGreater(rate(phase, '0x350'), 3 * rate('p', '0x350'))
        self.assertGreater(rate('p', '0x35c'), 4 * rate('e', '0x35c'))

    def test_physical_pl1_reduction_and_restore(self):
        records = load('cap-experiment')
        self.assertEqual(records[-1], {'kind': 'restoration', 'override_mw': 0,
                                       'effective_mw': 55000, 'ec_mw': 55000})
        rows = [r for r in records if r['kind'] == 'sample']
        means = {}
        for phase, override, effective in [('baseline', 0, 55000), ('limited', 35000, 35000), ('restored', 0, 55000)]:
            group = [r for r in rows if r['phase'] == phase]
            self.assertGreater(len(group), 100)
            tail = group[-50:]
            self.assertTrue(all(r['registers']['0x100'] == override for r in tail))
            self.assertTrue(all(r['registers']['0x160'] == effective for r in tail))
            means[phase] = statistics.mean(r['registers']['0x804'] for r in tail)
            if phase != 'baseline':
                self.assertLess(abs(means[phase] - effective), 3000)
        self.assertGreater(means['restored'] - means['limited'], 15000)
        for row in rows:
            self.assertTrue(all(row['registers'][f'0x{o:03x}'] == 0 for o in range(0x104, 0x120, 4)))
            self.assertLess(row['registers']['0x818'], 3600)

    def test_real_limit_level_moves_while_unknown_header_does_not(self):
        rows = [r for r in load('cap-experiment') if r['kind'] == 'sample']
        self.assertEqual({r['registers']['0x038'] for r in rows}, {1019})
        self.assertEqual({r['registers']['0x04c'] for r in rows}, {1})
        self.assertEqual({r['registers']['0x048'] for r in rows}, {1, 2})

    def test_package_pl2_and_system_pl2_regulate_the_fast_measurements(self):
        for name, offset, expected, status, slots in (
                ('package-cap-experiment', '0x804', 40000, 2, {0: 35000, 1: 40000}),
                ('system-cap-experiment', '0x814', 85000, 16, {4: 75000, 5: 85000})):
            with self.subTest(capture=name):
                records = load(name)
                rows = [r for r in records if r['kind'] == 'sample']
                tail = [r for r in rows if r['phase'] == 'limited'][-50:]
                self.assertLess(abs(statistics.mean(r['registers'][offset] for r in tail) - expected), 3000)
                self.assertTrue(all(r['registers']['0x048'] == status for r in tail))
                for slot, value in slots.items():
                    self.assertTrue(all(r['registers'][f'0x{0x160 + slot * 4:03x}'] == value for r in tail))
                    restored = records[-1]['slots'][str(slot)]
                    self.assertEqual(restored['override_mw'], 0)
                    self.assertEqual(restored['effective_mw'], restored['ec_mw'])

    def test_isolated_syspl1_eventually_regulates_and_restores(self):
        records = load('sustained-system-cap-experiment')
        rows = [r for r in records if r['kind'] == 'sample']
        limited = [r for r in rows if r['phase'] == 'limited']
        self.assertGreater(limited[-1]['elapsed_s'] - limited[0]['elapsed_s'], 79)
        tail = limited[-50:]
        self.assertTrue(all(r['registers']['0x048'] == 8 for r in tail))
        self.assertLess(abs(statistics.mean(r['registers']['0x814'] for r in tail) - 60000), 2000)
        self.assertLess(statistics.mean(r['registers']['0x62c'] for r in tail), 20000)
        self.assertTrue(all(r['registers']['0x110'] == 60000 for r in limited))
        self.assertTrue(all(r['registers']['0x114'] == 0 for r in rows))
        restored = records[-1]['slots']['4']
        self.assertEqual(restored['override_mw'], 0)
        self.assertEqual(restored['effective_mw'], restored['ec_mw'])
        workload = json.loads((DATA / 'sustained-system-cap-experiment-workload.json').read_text())
        self.assertGreater(workload['gpu_requests'], 20)

    def test_canonical_dgx_names_match_the_validated_control_and_energy_slots(self):
        registers = json.loads((DATA / 'dgx-directory-crosscheck.json').read_text())['registers']
        self.assertEqual(registers['SPBM_CPU_E_ENERGY_VALUE_ACCUMULATE_OFFSET'], 0x350)
        for name, slot in [('PL1', 0), ('PL2', 1), ('SYSPL1', 4), ('SYSPL2', 5)]:
            self.assertEqual(registers[f'SPBM_{name}_VAL_OS_OFFSET'], 0x100 + slot * 4)
            self.assertEqual(registers[f'SPBM_{name}_VAL_EC_OFFSET'], 0x120 + slot * 4)
            self.assertEqual(registers[f'SPBM_{name}_VAL_UEFI_OFFSET'], 0x140 + slot * 4)
            self.assertEqual(registers[f'SPBM_{name}_VAL_OFFSET'], 0x160 + slot * 4)
        self.assertEqual(registers['SPBM_PL_CUR_LEVEL_STATUS_OFFSET'], 0x48)
        self.assertEqual(registers['SPBM_PROCHOT_STATUS_OFFSET'], 0x4c)

    def test_independent_final_capture_confirms_all_overrides_cleared(self):
        for row in load('final-state-capture')[1:]:
            registers = row['registers']
            self.assertTrue(all(registers[f'0x{o:03x}'] == 0 for o in range(0x100, 0x120, 4)))
            for slot in (0, 1, 4, 5):
                self.assertEqual(registers[f'0x{0x120 + slot * 4:03x}'],
                                 registers[f'0x{0x160 + slot * 4:03x}'])
