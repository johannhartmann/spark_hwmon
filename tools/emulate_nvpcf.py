"""Execute pinned NVPCF helpers in emulated ARM64 RAM, without device access.

Only WDF context lookup and CFG dispatch are replaced by stubs. The indexed
helpers, offset table, copy routine and update store execute from vendor bytes.
"""
import struct

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2
from unicorn.arm64_const import UC_ARM64_REG_X30, UC_ARM64_REG_PC, UC_ARM64_REG_SP

from vendor_contract import load_pinned, NVPCF_SHA256


class NvpcfMachine:
    STACK = 0x100000
    OBJECT = 0x200000
    DEVICE = 0x201000
    FUNCTIONS = 0x210000
    CONTEXT = 0x220000
    MMIO = 0x300000  # ordinary emulated RAM, never a physical device mapping
    BUFFER = 0x320000
    STUBS = 0x400000
    STOP = STUBS + 0x100
    READ = 0xcd28
    WRITE = 0xce68
    UPDATE = 0xcfa8

    def __init__(self, binary, mapping=True, contexts=None):
        pe = load_pinned(binary, NVPCF_SHA256)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        image = pe.get_memory_mapped_image()
        self.uc.mem_map(self.base, (len(image) + 4095) & ~4095)
        self.uc.mem_write(self.base, image)
        for address, size in [(self.STACK, 0x10000), (self.OBJECT, 0x3000),
                              (self.FUNCTIONS, 0x1000), (self.CONTEXT, 0x1000),
                              (self.MMIO, 0x1000), (self.BUFFER, 0x3000),
                              (self.STUBS, 0x1000)]:
            self.uc.mem_map(address, size)
        self.contexts = list(contexts) if contexts is not None else [self.CONTEXT] * 2
        self.writes = []
        self.reads = []
        self.put64(self.base + 0x44988, self.OBJECT)
        self.put64(self.OBJECT + 0x1b0, self.DEVICE)
        self.put64(self.DEVICE + 0x50, self.OBJECT)
        self.put64(self.base + 0x448c8, self.FUNCTIONS)
        self.put64(self.FUNCTIONS + 0x650, self.STUBS)
        self.put64(self.base + 0x3d410, self.STUBS + 0x10)
        self.put64(self.CONTEXT + 0xb50, self.MMIO if mapping else 0)
        self.uc.hook_add(UC_HOOK_CODE, self._stub, begin=self.STUBS, end=self.STUBS + 0x20)
        self.uc.hook_add(UC_HOOK_MEM_READ, self._read, begin=self.MMIO,
                         end=self.MMIO + 0xfff)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._write, begin=self.MMIO,
                         end=self.MMIO + 0xfff)

    def put64(self, address, value):
        self.uc.mem_write(address, struct.pack('<Q', value))

    def _stub(self, uc, address, size, user_data):
        if address == self.STUBS:
            uc.reg_write(UC_ARM64_REG_X0, self.contexts.pop(0))
        elif address != self.STUBS + 0x10:
            raise AssertionError(f'Unexpected stub: {address:#x}')
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))

    def _read(self, uc, access, address, size, value, user_data):
        self.reads.append((address - self.MMIO, size))

    def _write(self, uc, access, address, size, value, user_data):
        self.writes.append((address - self.MMIO, size, value))

    def run(self, helper, index=0, length=4, buffer=None):
        uc = self.uc
        uc.reg_write(UC_ARM64_REG_SP, self.STACK + 0xf000)
        uc.reg_write(UC_ARM64_REG_X30, self.STOP)
        uc.reg_write(UC_ARM64_REG_X0, index & ((1 << 64) - 1))
        uc.reg_write(UC_ARM64_REG_X1, self.BUFFER if buffer is None else buffer)
        uc.reg_write(UC_ARM64_REG_X2, length)
        uc.emu_start(self.base + helper, self.STOP, count=20000)
        if uc.reg_read(UC_ARM64_REG_PC) != self.STOP:
            raise AssertionError('Vendor helper did not return within the instruction limit')
        return uc.reg_read(UC_ARM64_REG_X0)
