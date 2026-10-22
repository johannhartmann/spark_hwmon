"""Version-pinned facts extracted from the two acquired Windows ARM64 drivers."""
import hashlib
import struct
import uuid
from pathlib import Path

import pefile

NVPCF_SHA256 = '530ea7f04474a1a95ba71d8397bbc3b48b210dd58fd7b7892256c705e1c36ef0'
MTEL_SHA256 = '7028cd64cdcced2382181cf29c7f9f6f21abf192412870c0e866d8e137cefced'
MTEL_GUID = '12345678-1234-1234-1234-123456789abc'
ALIASES = (
    ('CFL', 'CPUEB_FASTDVFS_LOG_OFFSET', 0x398, 0x448, 0x800),
    ('CPL', 'CPUEB_PERFCNT_LOG_OFFSET', 0x39c, 0x450, 0x400),
    ('CBL', 'CPUEB_BPT_LOG_OFFSET', 0x3a0, 0x458, 0x400),
    ('CCI', 'CPUEB_CPPC_INTERFACE_OFFSET', 0x3a4, 0x460, 0x1000),
    ('CPI', 'CPUEB_PL_INTERFACE_OFFSET', 0x3a8, 0x468, 0x1000),
    ('CTS0', 'CPUEB_TJPID_SLAVE0_OFFSET', 0x3ac, 0x470, 0x400),
    ('CTS1', 'CPUEB_TJPID_SLAVE1_OFFSET', 0x3b0, 0x478, 0x400),
)


def load_pinned(path, digest):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'Unsupported binary hash: {path}')
    pe = pefile.PE(data=data)
    if pe.FILE_HEADER.Machine != 0xaa64:
        raise ValueError('Expected ARM64 PE')
    return pe


def extract(nvpcf_path, mtel_path):
    nvpcf = load_pinned(nvpcf_path, NVPCF_SHA256)
    mtel = load_pinned(mtel_path, MTEL_SHA256)
    offsets = struct.unpack('<48I', nvpcf.get_data(0x3dc70, 48 * 4))
    if any(offset % 4 or offset > 0xffc for offset in offsets):
        raise ValueError('Invalid offset directory')
    raw = mtel.__data__
    for short, long_name, *_ in ALIASES:
        if short.encode() + b'\0' not in raw or long_name.encode() + b'\0' not in raw:
            raise ValueError(f'Missing directory alias: {short}')
    if mtel.get_data(0x2fa70, 16) != uuid.UUID(MTEL_GUID).bytes_le:
        raise ValueError('Unexpected MTEL GUID location')
    ioctls = []
    for index in range(4):
        code, minimum_input, minimum_output, callback, admin = struct.unpack(
            '<III4xQB7x', mtel.get_data(0x33720 + index * 32, 32))
        ioctls.append({'code': code, 'minimum_input_bytes': minimum_input,
                       'minimum_output_bytes': minimum_output,
                       'callback_rva': callback - mtel.OPTIONAL_HEADER.ImageBase,
                       'per_ioctl_administrator_flag': bool(admin)})
    parameters = struct.unpack('<24I', nvpcf.get_data(0x3dc10, 96))
    return {
        'nvpcf_sha256': NVPCF_SHA256,
        'mtel_sha256': MTEL_SHA256,
        'physical_base': 0x1c238000,
        'requested_mapping_bytes': 0x814,
        'offset_table_rva': 0x3dc70,
        'registers': [{'index': i, 'offset': offset} for i, offset in enumerate(offsets)],
        'mtel_guid': MTEL_GUID,
        'mtel_device_interface_guid': str(uuid.UUID(bytes_le=mtel.get_data(0x2fa80, 16))),
        'mtel_ioctl_record_rva': 0x33720,
        'mtel_ioctls': ioctls,
        'nvpcf_raw_parameter_records': [list(parameters[i:i + 3])
                                         for i in range(0, len(parameters), 3)],
        'cpueb_tables': [dict(zip(
            ('key', 'alias', 'context_offset', 'mapping_pointer_offset', 'mapping_bytes'), item
        )) for item in ALIASES],
    }


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('nvpcf', type=Path)
    parser.add_argument('mtel', type=Path)
    args = parser.parse_args()
    try:
        result = extract(args.nvpcf, args.mtel)
    except (OSError, ValueError, pefile.PEFormatError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))
