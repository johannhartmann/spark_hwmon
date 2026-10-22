"""Opt-in tests execute original vendor helpers in an isolated ARM64 emulator.

Set SPBM_VENDOR_DIR to the acquired Windows-package research directory and
install tools/requirements.txt. Proprietary binaries are not part of this repo.
"""
import os
from pathlib import Path
import struct
import sys
import unittest

VENDOR_ROOT = os.environ.get('SPBM_VENDOR_DIR')


@unittest.skipUnless(VENDOR_ROOT, 'set SPBM_VENDOR_DIR to test acquired Windows binaries')
class VendorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
        from vendor_contract import extract
        from emulate_nvpcf import NvpcfMachine
        from emulate_mtel import MtelMachine
        root = Path(VENDOR_ROOT)
        cls.nvpcf = root / 'nvidia-617.42-extracted/NVPCF/nvpcf.sys'
        cls.mtel = next((root / 'asus-winre-drivers').rglob('nvMeTelemetryKMD.sys'))
        cls.contract = extract(cls.nvpcf, cls.mtel)
        cls.machine = NvpcfMachine
        cls.parser = MtelMachine

    def test_artifact_identity_rejects_another_driver_version(self):
        from vendor_contract import load_pinned
        with self.assertRaises(ValueError):
            load_pinned(self.nvpcf, '0' * 64)

    def test_capture_offsets_include_the_extracted_vendor_directory(self):
        import importlib.util
        script = Path(__file__).resolve().parent.parent / 'tools/capture-n1x.py'
        spec = importlib.util.spec_from_file_location('capture_n1x', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(tuple(item['offset'] for item in self.contract['registers']),
                         module.VENDOR_OFFSETS)
        self.assertTrue(all(0 <= offset <= 0xffc and offset % 4 == 0
                            for offset in module.OFFSETS))

    def test_original_indexed_reads_all_48_fields(self):
        for item in self.contract['registers']:
            with self.subTest(index=item['index']):
                m = self.machine(self.nvpcf)
                expected = 0x76540000 + item['index']
                m.uc.mem_write(m.MMIO + item['offset'], struct.pack('<I', expected))
                self.assertEqual(m.run(m.READ, item['index']), 0)
                self.assertEqual(struct.unpack('<I', m.uc.mem_read(m.BUFFER, 4))[0], expected)
                self.assertEqual(m.writes, [])
                self.assertEqual(sum(size for _, size in m.reads), 4)
                self.assertTrue(all(item['offset'] <= offset and offset + size <= item['offset'] + 4
                                    for offset, size in m.reads))

    def test_original_indexed_writes_all_48_fields_in_emulated_ram(self):
        for item in self.contract['registers']:
            with self.subTest(index=item['index']):
                m = self.machine(self.nvpcf)
                expected = 0x12340000 + item['index']
                m.uc.mem_write(m.BUFFER, struct.pack('<I', expected))
                self.assertEqual(m.run(m.WRITE, item['index']), 0)
                self.assertEqual(struct.unpack('<I', m.uc.mem_read(m.MMIO + item['offset'], 4))[0], expected)
                self.assertEqual(m.writes, [(item['offset'] + i, 1, byte)
                                            for i, byte in enumerate(struct.pack('<I', expected))])
                self.assertEqual(m.uc.mem_read(m.MMIO, 4), b'\0' * 4)
                self.assertEqual(m.reads, [])

    def test_original_update_store_is_separate(self):
        m = self.machine(self.nvpcf)
        self.assertEqual(m.run(m.UPDATE), 0)
        self.assertEqual(m.writes, [(0, 4, 1)])

    def test_original_descriptor_reads_spbm_without_update(self):
        m = self.machine(self.nvpcf)
        m.uc.mem_write(m.MMIO + 0x310, struct.pack('<I', 745))
        # Descriptor byte 9: SPBM bus 5; byte 10: length; byte 11: read 0.
        descriptor = (5 << 8) | (4 << 16)
        self.assertEqual(m.run(0x216d0, index=40, buffer=descriptor,
                               length=m.BUFFER), 0)
        self.assertEqual(m.uc.mem_read(m.BUFFER, 8), struct.pack('<Q', 745))
        self.assertEqual(m.writes, [])

    def test_original_descriptor_writes_then_updates_in_emulated_ram(self):
        for index in range(8):
            with self.subTest(index=index):
                m = self.machine(self.nvpcf, contexts=[self.machine.CONTEXT] * 4)
                m.put64(m.BUFFER, index)
                descriptor = (5 << 8) | (4 << 16) | (2 << 24)
                self.assertEqual(m.run(0x216d0, index=45000, buffer=descriptor,
                                       length=m.BUFFER), 0)
                offset = 0x100 + index * 4
                expected = [(offset + i, 1, byte)
                            for i, byte in enumerate(struct.pack('<I', 45000))]
                self.assertEqual(m.writes, expected + [(0, 4, 1)])

    def test_original_descriptor_does_not_commit_a_failed_write(self):
        for index, direction, expected in ((48, 2, 0x3b), (0, 1, 0x56)):
            with self.subTest(index=index, direction=direction):
                m = self.machine(self.nvpcf)
                m.put64(m.BUFFER, index)
                descriptor = (5 << 8) | (4 << 16) | (direction << 24)
                self.assertEqual(m.run(0x216d0, index=45000, buffer=descriptor,
                                       length=m.BUFFER), expected)
                self.assertEqual(m.writes, [])

    def test_original_rejects_invalid_indices_without_access(self):
        for helper in (self.machine.READ, self.machine.WRITE):
            for index in (48, 49, 0xffffffff, -1):
                with self.subTest(helper=helper, index=index):
                    m = self.machine(self.nvpcf)
                    self.assertEqual(m.run(helper, index), 0x3b)
                    self.assertEqual(m.writes, [])
                    self.assertEqual(m.reads, [])

    def test_original_missing_mapping_is_reported(self):
        for helper in (self.machine.READ, self.machine.WRITE, self.machine.UPDATE):
            with self.subTest(helper=helper):
                m = self.machine(self.nvpcf, mapping=False)
                self.assertEqual(m.run(helper), 0x40)
                self.assertEqual(m.writes, [])

    def test_original_missing_wdf_context_is_reported(self):
        for contexts, status in (([0], 0x3d), ([self.machine.CONTEXT, 0], 0x40)):
            for helper in (self.machine.READ, self.machine.WRITE, self.machine.UPDATE):
                with self.subTest(contexts=contexts, helper=helper):
                    m = self.machine(self.nvpcf, contexts=contexts)
                    self.assertEqual(m.run(helper), status)
                    self.assertEqual(m.writes, [])

    def test_original_zero_length_and_null_write_are_noops(self):
        for helper in (self.machine.READ, self.machine.WRITE):
            m = self.machine(self.nvpcf)
            self.assertEqual(m.run(helper, length=0), 0)
            self.assertEqual(m.writes, [])
        m = self.machine(self.nvpcf)
        self.assertEqual(m.run(m.WRITE, buffer=0), 0)
        self.assertEqual(m.writes, [])

    def test_original_helpers_allow_multifield_copy(self):
        m = self.machine(self.nvpcf)
        values = struct.pack('<III', 123, 456, 789)
        m.uc.mem_write(m.MMIO + 0x344, values)
        self.assertEqual(m.run(m.READ, index=43, length=12), 0)
        self.assertEqual(m.uc.mem_read(m.BUFFER, 12), values)
        self.assertEqual(m.writes, [])

    def test_original_helper_does_not_bound_copy_to_mapping_size(self):
        # A caller-supplied length crosses the fake MMIO guard page. This
        # establishes why a Linux port must impose its own strict bounds.
        from unicorn import UcError
        m = self.machine(self.nvpcf)
        with self.assertRaises(UcError):
            m.run(m.READ, index=47, length=0x1000)
        self.assertEqual(m.writes, [])

    def test_original_mtel_maps_relative_and_absolute_tables(self):
        from vendor_contract import ALIASES
        offsets = dict(CFL=0x5ac00, CPL=0x5a400, CBL=0x5a600, CCI=0x5c404,
                       CPI=0x5b400, CTS0=0x0539a000, CTS1=0x0b39a000)
        status, maps = self.parser(self.mtel).map_tables(offsets)
        self.assertEqual(status, 0)
        expected = [(offsets[key] + (0 if key.startswith('CTS') else 0x05170000), size)
                    for key, _, _, _, size in ALIASES]
        self.assertCountEqual(maps, expected)

    def test_original_mtel_parser_accepts_all_short_and_long_keys(self):
        from vendor_contract import ALIASES
        for short, long_name, *_ in ALIASES:
            for key in (short, long_name):
                with self.subTest(key=key):
                    m = self.parser(self.mtel)
                    result = m.parse(key, value=0x5a400, expected=key)
                    self.assertEqual(result, {'status': 0, 'value': 0x5a400,
                                              'consumed': len(key) + 1 + 12})

    def test_original_mtel_parser_rejects_wrong_key_without_advancing(self):
        result = self.parser(self.mtel).parse('CPL', expected='CFL')
        self.assertTrue(result['status'] & 0x80000000)
        self.assertEqual(result['value'], 0xa5a5a5a5)
        self.assertEqual(result['consumed'], 0)

    def test_original_mtel_parser_rejects_null_arguments(self):
        for argument in range(3):
            with self.subTest(argument=argument):
                result = self.parser(self.mtel).parse('CFL', null_arg=argument)
                self.assertEqual(result['status'], 0xc000000d)
                self.assertEqual(result['value'], 0xa5a5a5a5)


if __name__ == '__main__':
    unittest.main()
