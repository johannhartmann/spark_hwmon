"""Compile and exercise the actual production ACPI helpers against host fixtures."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class DriverHelperTests(unittest.TestCase):
    def test_production_acpi_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = str(Path(directory) / 'acpi-tests')
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            '-Wno-sign-compare', str(ROOT / 'tests/test_n1x_acpi.c'),
                            '-o', binary], check=True)
            subprocess.run([binary], check=True)

    def test_dkms_and_loaded_module_version_match(self):
        dkms = re.search(r'PACKAGE_VERSION="([^"]+)"', (ROOT / 'dkms.conf').read_text())[1]
        module = re.search(r'MODULE_VERSION\("([^"]+)"\)', (ROOT / 'spbm.c').read_text())[1]
        self.assertEqual(dkms, module)


if __name__ == '__main__':
    unittest.main()
