"""Check the committed read-only P16 evidence, without accessing hardware."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'docs/validation'
spec = importlib.util.spec_from_file_location('recorded_analysis', ROOT / 'tools/analyze-n1x.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class RecordedHardwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.captures = {name: analysis.load(DATA / f'{name}-capture.jsonl.gz')
                        for name in ('load', 'legacy-load')}

    def test_capture_integrity_and_report_reproduction(self):
        manifest = json.loads((DATA / 'manifest.json').read_text())
        for name, records in self.captures.items():
            with self.subTest(capture=name):
                path = DATA / f'{name}-capture.jsonl.gz'
                expected = manifest[path.name]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected['sha256_gzip'])
                self.assertEqual(hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest(), expected['sha256_jsonl'])
                self.assertEqual(len(records) - 1, expected['samples'])
                self.assertEqual(analysis.summarize(records),
                                 json.loads((DATA / f'{name}-report.json').read_text()))

    def test_direct_registers_agree_with_existing_acpi_backend(self):
        temperatures = {0x818: 'soc', 0x820: 'cpu_e_clu0', 0x824: 'cpu_p_clu0',
                        0x828: 'cpu_e_clu1', 0x82c: 'cpu_p_clu1', 0x830: 'gpu',
                        0x834: 'uncore', 0x838: 'dla'}
        for name, records in self.captures.items():
            for index, row in enumerate(records[1:]):
                with self.subTest(capture=name, sample=index):
                    for offset, label in temperatures.items():
                        self.assertLessEqual(abs(row['registers'][f'0x{offset:03x}'] * 100 -
                                                 273150 - row['hwmon'][label]), 500)
                    for offset, label in ((0x800, 'soc_pkg'), (0x80c, 'sys_total')):
                        self.assertLessEqual(abs(row['registers'][f'0x{offset:03x}'] * 1000 -
                                                 row['hwmon'][label]), 20000)

    def test_separate_cpu_and_cuda_loads_change_the_candidate_rails(self):
        for name, records in self.captures.items():
            phases = {p['phase']: p for p in analysis.summarize(records)['phases']}
            with self.subTest(capture=name):
                idle = phases['idle']['registers']
                self.assertGreater(phases['cpu']['registers']['0x30c']['mean'],
                                   5 * idle['0x30c']['mean'])
                self.assertGreater(phases['gpu']['registers']['0x324']['mean'],
                                   1.5 * idle['0x324']['mean'])

    def test_energy_relationships_preserve_the_unresolved_e_core_mismatch(self):
        for name, records in self.captures.items():
            for phase in analysis.summarize(records)['phases']:
                with self.subTest(capture=name, phase=phase['phase']):
                    checks = phase['candidate_energy_checks']
                    for key, tolerance in (('package_vs_804', .03), ('cpu_p', .15), ('gpu', .10)):
                        self.assertLessEqual(abs(checks[key]['ratio_if_mJ_and_mW'] - 1), tolerance)
                        self.assertEqual(checks[key]['counter_decreases'], 0)
                    # This is a measured disagreement, not a successful unit validation.
                    self.assertGreater(checks['cpu_e']['ratio_if_mJ_and_mW'], 1.4)

    def test_no_os_limit_overrides_observed_during_capture(self):
        for records in self.captures.values():
            for row in records[1:]:
                self.assertTrue(all(row['registers'][f'0x{offset:03x}'] == 0
                                    for offset in range(0x100, 0x120, 4)))
