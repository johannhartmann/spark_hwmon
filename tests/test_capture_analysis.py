import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'n1x_analysis', Path(__file__).resolve().parent.parent / 'tools/analyze-n1x.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def records(first=0, last=32):
    return [{'kind': 'metadata'},
            {'kind': 'sample', 'monotonic_s': 10, 'phase': 'idle',
             'registers': {'0x344': first, '0x804': 32}},
            {'kind': 'sample', 'monotonic_s': 11, 'phase': 'idle',
             'registers': {'0x344': last, '0x804': 32}}]


class CaptureAnalysisTests(unittest.TestCase):
    def test_known_energy_power_relationship(self):
        report = analysis.summarize(records())
        check = report['phases'][0]['candidate_energy_checks']['package_vs_804']
        self.assertEqual(check['ratio_if_mJ_and_mW'], 1)
        self.assertEqual(check['counter_decreases'], 0)

    def test_u32_rollover_is_explicit(self):
        report = analysis.summarize(records(0xfffffff0, 0x10))
        check = report['phases'][0]['candidate_energy_checks']['package_vs_804']
        self.assertEqual(check['counter_delta_mod_u32'], 32)
        self.assertEqual(check['counter_decreases'], 1)

    def test_uneven_intervals_use_actual_time_and_trapezoids(self):
        data = records(0, 60)
        data[1]['registers']['0x804'] = 20
        data[2]['registers']['0x804'] = 40
        data[2]['monotonic_s'] = 12
        check = analysis.summarize(data)['phases'][0]['candidate_energy_checks']['package_vs_804']
        self.assertEqual(check['power_time_integral_raw'], 60)
        self.assertEqual(check['ratio_if_mJ_and_mW'], 1)

    def test_repeated_phase_does_not_integrate_through_other_load(self):
        data = records()
        middle = copy.deepcopy(data[-1]); middle.update(phase='cpu', monotonic_s=12)
        end = copy.deepcopy(data[-1]); end.update(monotonic_s=13)
        data += [middle, end]
        phases = analysis.summarize(data)['phases']
        self.assertEqual([p['phase'] for p in phases], ['idle', 'cpu', 'idle'])
        self.assertEqual(phases[-1]['candidate_energy_checks'], {})

    def test_zero_power_is_not_reported_as_valid_match(self):
        data = records()
        for row in data[1:]: row['registers']['0x804'] = 0
        check = analysis.summarize(data)['phases'][0]['candidate_energy_checks']['package_vs_804']
        self.assertIsNone(check['ratio_if_mJ_and_mW'])

    def test_bad_times_and_register_values_are_rejected(self):
        for field, value in [('monotonic_s', 10), ('monotonic_s', float('nan')),
                             ('monotonic_s', float('inf'))]:
            data = records(); data[2][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                analysis.summarize(data)
        for value in [-1, 2**32, True, 3.5]:
            data = records(); data[2]['registers']['0x344'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                analysis.summarize(data)

    def test_missing_metadata_or_samples_are_rejected(self):
        for data in ([], records()[1:], records()[:2]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                analysis.summarize(data)
