#!/usr/bin/env python3
"""Inspect vendor PE files without loading or executing them.

Requires pefile; --code additionally requires capstone. Output is JSON.
"""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

import pefile


def inspect(path, code=None):
    data = path.read_bytes()
    pe = pefile.PE(data=data)
    base = pe.OPTIONAL_HEADER.ImageBase
    result = {
        'file': path.name,
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'machine': hex(pe.FILE_HEADER.Machine),
        'image_base': hex(base),
        'versions': {},
        'pdb': [],
        'guid_matches': [],
        'imports': [],
    }
    for group in getattr(pe, 'FileInfo', []):
        for info in group:
            for table in getattr(info, 'StringTable', []):
                for key in (b'CompanyName', b'FileVersion', b'ProductVersion', b'FileDescription'):
                    if key in table.entries:
                        result['versions'][key.decode()] = table.entries[key].decode(errors='replace')
    for entry in getattr(pe, 'DIRECTORY_ENTRY_DEBUG', []):
        offset = entry.struct.PointerToRawData
        record = data[offset:offset + entry.struct.SizeOfData]
        if record[:4] == b'RSDS' and len(record) >= 24:
            result['pdb'].append({
                'path': record[24:].rstrip(b'\0').decode(errors='replace'),
                'guid': uuid.UUID(bytes_le=record[4:20]).hex.upper(),
                'age': int.from_bytes(record[20:24], 'little'),
            })
    for name, value in (
        ('mtel', '12345678-1234-1234-1234-123456789abc'),
        ('npcf', '36b49710-2483-11e7-9598-0800200c9a66'),
    ):
        offset = data.find(uuid.UUID(value).bytes_le)
        if offset >= 0:
            result['guid_matches'].append({
                'name': name, 'guid': value, 'file_offset': hex(offset),
                'rva': hex(pe.get_rva_from_offset(offset)),
            })
    for library in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
        for entry in library.imports:
            result['imports'].append({
                'library': library.dll.decode(errors='replace'),
                'name': entry.name.decode(errors='replace') if entry.name else entry.ordinal,
                'iat_rva': hex(entry.address - base),
            })
    if code:
        import capstone
        if pe.FILE_HEADER.Machine != 0xaa64:
            raise ValueError('--code requires an ARM64 PE file')
        rva, length = (int(part, 0) for part in code.split(':'))
        if not 0 < length <= 4096:
            raise ValueError('Code length must be 1..4096 bytes')
        decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        result['code'] = [
            {'rva': hex(ins.address - base), 'instruction': f'{ins.mnemonic} {ins.op_str}'}
            for ins in decoder.disasm(pe.get_data(rva, length), base + rva)
        ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--code', metavar='RVA:LENGTH', help='disassemble a bounded ARM64 range')
    args = parser.parse_args()
    try:
        result = inspect(args.file, args.code)
    except (OSError, ValueError, pefile.PEFormatError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
