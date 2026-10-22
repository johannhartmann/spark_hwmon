"""Run pinned MTEL directory, platform and SPBM reader helpers in emulator RAM."""
import struct

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2
from unicorn.arm64_const import UC_ARM64_REG_X30, UC_ARM64_REG_PC, UC_ARM64_REG_SP

from vendor_contract import load_pinned, MTEL_SHA256


class MtelMachine:
    STACK = 0x100000
    BUFFER = 0x200000
    STOP = 0x300000
    PARSE_FIELD = 0x1a6c8
    MAP_TABLES = 0x13b0
    CONTEXT = 0x210000
    FUNCTIONS = 0x220000
    MMIO = 0x400000  # ordinary emulator RAM

    def __init__(self, binary):
        pe = load_pinned(binary, MTEL_SHA256)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        image = pe.get_memory_mapped_image()
        self.uc.mem_map(self.base, (len(image) + 4095) & ~4095)
        self.uc.mem_write(self.base, image)
        self.uc.mem_map(self.STACK, 0x10000)
        self.uc.mem_map(self.BUFFER, 0x3000)
        self.uc.mem_map(self.STOP, 0x1000)
        self.uc.mem_map(self.CONTEXT, 0x1000)
        self.uc.mem_map(self.FUNCTIONS, 0x1000)
        self.uc.mem_map(self.MMIO, 0x1000)
        self.maps = []
        # Disable WPP tracing using the driver's normal self-linked sentinel.
        address = self.base + 0x33ad8
        self.uc.mem_write(address, struct.pack('<Q', address))
        self.uc.mem_write(self.base + 0x2e1c0, struct.pack('<Q', self.STOP + 0x10))
        self.uc.hook_add(UC_HOOK_CODE, self._strcmp,
                         begin=self.STOP + 0x10, end=self.STOP + 0x10)

    def _run(self, rva, x0, x1=0):
        uc = self.uc
        uc.reg_write(UC_ARM64_REG_SP, self.STACK + 0xf000)
        uc.reg_write(UC_ARM64_REG_X30, self.STOP)
        uc.reg_write(UC_ARM64_REG_X0, x0)
        uc.reg_write(UC_ARM64_REG_X1, x1)
        uc.emu_start(self.base + rva, self.STOP, count=20000)
        if uc.reg_read(UC_ARM64_REG_PC) != self.STOP:
            raise AssertionError('MTEL helper did not return')
        return uc.reg_read(UC_ARM64_REG_X0)

    def platform_layout(self, platform):
        """Execute the vendor platform selector and register-layout copier."""
        if platform not in (1, 2, 3):
            raise ValueError('Expected vendor platform ID 1, 2 or 3')
        if self._run(0x38668, platform) or self._run(0x387b0, self.CONTEXT + 0x14):
            raise AssertionError('Vendor platform initialization failed')
        return struct.unpack('<223I', self.uc.mem_read(self.CONTEXT + 0x14, 0x37c))

    def read_spbm(self, kind, values, platform=2):
        """Execute complete status/energy readers, with WDF replaced by stubs.

        Input values populate emulator RAM. This method never maps a device.
        Reads and writes record the original helper's memory accesses.
        """
        rva, words = {'status': (0x134e0, 2), 'energy': (0x138a0, 15),
                      'power': (0x131d0, 16)}[kind]
        self.platform_layout(platform)
        uc = self.uc
        for offset, value in values.items():
            if offset % 4 or not 0 <= offset <= 0xffc:
                raise ValueError('Invalid emulated register offset')
            uc.mem_write(self.MMIO + offset, struct.pack('<I', value))
        def put64(address, value):
            uc.mem_write(address, struct.pack('<Q', value))
        put64(self.base + 0x33fb8, self.FUNCTIONS)
        put64(self.FUNCTIONS + 0x650, self.STOP + 0x20)
        put64(self.base + 0x2e1d0, self.STOP + 0x30)
        put64(self.CONTEXT + 0x570, self.MMIO)
        put64(self.BUFFER + 8, self.BUFFER + 0x100)
        reads, writes = [], []
        def record_read(u, access, address, size, value, data):
            reads.append((address - self.MMIO, size))
        def record_write(u, access, address, size, value, data):
            writes.append((address - self.MMIO, size, value))
        hooks = [uc.hook_add(UC_HOOK_CODE, self._mapping_stub,
                             begin=self.STOP + 0x20, end=self.STOP + 0x30),
                 uc.hook_add(UC_HOOK_MEM_READ, record_read,
                             begin=self.MMIO, end=self.MMIO + 0xfff),
                 uc.hook_add(UC_HOOK_MEM_WRITE, record_write,
                             begin=self.MMIO, end=self.MMIO + 0xfff)]
        try:
            status = self._run(rva, self.CONTEXT, self.BUFFER)
        finally:
            for hook in hooks:
                uc.hook_del(hook)
        result = struct.unpack(f'<{words}I', uc.mem_read(self.BUFFER + 0x100, words * 4))
        return status, result, reads, writes

    def _strcmp(self, uc, address, size, user_data):
        def string(pointer):
            result = bytearray()
            for offset in range(4096):
                byte = uc.mem_read(pointer + offset, 1)[0]
                if not byte:
                    return bytes(result)
                result.append(byte)
            raise AssertionError('Unterminated emulated strcmp argument')
        first = string(uc.reg_read(UC_ARM64_REG_X0))
        second = string(uc.reg_read(UC_ARM64_REG_X1))
        value = (first > second) - (first < second)
        uc.reg_write(UC_ARM64_REG_X0, value & 0xffffffff)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))

    def _mapping_stub(self, uc, address, size, user_data):
        if address == self.STOP + 0x20:
            uc.reg_write(UC_ARM64_REG_X0, self.CONTEXT)
        elif address == self.STOP + 0x40:
            self.maps.append((uc.reg_read(UC_ARM64_REG_X0), uc.reg_read(UC_ARM64_REG_X1)))
            uc.reg_write(UC_ARM64_REG_X0, 0x500000 + len(self.maps) * 0x2000)
        elif address != self.STOP + 0x30:
            raise AssertionError('Unexpected mapping stub')
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))

    def map_tables(self, offsets, base=0x05170000):
        from vendor_contract import ALIASES
        uc = self.uc
        def put64(address, value):
            uc.mem_write(address, struct.pack('<Q', value))
        put64(self.base + 0x33fb8, self.FUNCTIONS)
        put64(self.FUNCTIONS + 0x650, self.STOP + 0x20)
        put64(self.base + 0x2e1d0, self.STOP + 0x30)
        put64(self.base + 0x2e180, self.STOP + 0x40)
        uc.hook_add(UC_HOOK_CODE, self._mapping_stub,
                    begin=self.STOP + 0x20, end=self.STOP + 0x40)
        uc.mem_write(self.CONTEXT + 0x390, struct.pack('<II', base, 0x60000))
        for key, _, context_offset, _, _ in ALIASES:
            uc.mem_write(self.CONTEXT + context_offset, struct.pack('<I', offsets[key]))
        uc.reg_write(UC_ARM64_REG_SP, self.STACK + 0xf000)
        uc.reg_write(UC_ARM64_REG_X30, self.STOP)
        uc.reg_write(UC_ARM64_REG_X0, self.CONTEXT)
        uc.emu_start(self.base + self.MAP_TABLES, self.STOP, count=20000)
        if uc.reg_read(UC_ARM64_REG_PC) != self.STOP:
            raise AssertionError('MTEL mapper did not return')
        return uc.reg_read(UC_ARM64_REG_X0), self.maps

    def parse(self, key, value=0x5ac00, expected='CFL', null_arg=None):
        uc = self.uc
        cursor = self.BUFFER + 0x100
        payload = self.BUFFER + 0x200
        wanted = self.BUFFER + 0x1000
        output = self.BUFFER + 0x1100
        # Cursor starts at an ACPI string argument's data, not its header.
        data = key.encode() + b'\0' + struct.pack('<HHIHH', 0, 4, value, 1, 4)
        uc.mem_write(payload, data)
        uc.mem_write(cursor, struct.pack('<Q', payload))
        uc.mem_write(wanted, expected.encode() + b'\0')
        uc.mem_write(output, struct.pack('<I', 0xa5a5a5a5))
        args = [cursor, wanted, output]
        if null_arg is not None:
            args[null_arg] = 0
        for reg, value in zip((UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2), args):
            uc.reg_write(reg, value)
        uc.reg_write(UC_ARM64_REG_SP, self.STACK + 0xf000)
        uc.reg_write(UC_ARM64_REG_X30, self.STOP)
        uc.emu_start(self.base + self.PARSE_FIELD, self.STOP, count=20000)
        if uc.reg_read(UC_ARM64_REG_PC) != self.STOP:
            raise AssertionError('MTEL parser did not return within the instruction limit')
        return {
            'status': uc.reg_read(UC_ARM64_REG_X0),
            'value': struct.unpack('<I', uc.mem_read(output, 4))[0],
            'consumed': struct.unpack('<Q', uc.mem_read(cursor, 8))[0] - payload,
        }
