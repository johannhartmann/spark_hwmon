"""Portable tests for the hardware validation tool's optional-channel handling."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('runtime_check', Path(__file__).with_name('check-n1x.py'))
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class RuntimeCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def sensor(self, name, label, value):
        (self.root / f'{name}_label').write_text(label)
        (self.root / f'{name}_input').write_text(str(value))

    def test_missing_optional_temperature_channels(self):
        self.sensor('power1', 'sys_total', 15000000)
        self.assertEqual(checker.check(self.root), {'sys_total': 15000000})

    def test_missing_optional_power_channels(self):
        self.sensor('temp6', 'gpu', 45000)
        self.assertEqual(checker.check(self.root), {'gpu': 45000})

    def test_require_all_detects_missing_channels(self):
        self.sensor('temp6', 'gpu', 45000)
        with self.assertRaises(ValueError):
            checker.check(self.root, require_all=True)

    def test_empty_device_rejected(self):
        with self.assertRaises(ValueError):
            checker.check(self.root)

    def test_power_control_rejected(self):
        self.sensor('power1', 'sys_total', 15000000)
        (self.root / 'power1_cap').write_text('10000000')
        with self.assertRaises(ValueError):
            checker.check(self.root)

    def test_wrong_sensor_class_rejected(self):
        self.sensor('temp1', 'sys_total', 15000000)
        with self.assertRaises(ValueError):
            checker.check(self.root)

    def test_duplicate_label_rejected(self):
        self.sensor('temp1', 'gpu', 45000)
        self.sensor('temp2', 'gpu', 45000)
        with self.assertRaises(ValueError):
            checker.check(self.root)

    def test_firmware_sentinel_rejected(self):
        self.sensor('power1', 'sys_total', 0xffffffff * 1000)
        with self.assertRaises(ValueError):
            checker.check(self.root)

    def test_disagreement_with_thermal_zone_rejected(self):
        self.sensor('temp1', 'gpu', 45000)
        zone = self.root / 'thermal_zone0'
        zone.mkdir()
        (zone / 'type').write_text('TGPU')
        (zone / 'temp').write_text('65000')
        with self.assertRaises(ValueError):
            checker.check(self.root, thermal=self.root)

    def test_absent_optional_zone_does_not_fail_comparison(self):
        self.sensor('temp1', 'gpu', 45000)
        zone = self.root / 'thermal_zone0'
        zone.mkdir()
        (zone / 'type').write_text('TS0E')
        (zone / 'temp').write_text('65000')
        self.assertEqual(checker.check(self.root, thermal=self.root), {'gpu': 45000})


if __name__ == '__main__':
    unittest.main()
