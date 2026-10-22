# Windows ARM64 vendor drivers for N1X reverse engineering

The matching Windows vendor implementation has been obtained. A separate Linux
vendor driver or a published register specification is not required to continue:
the next step is static analysis of these Windows ARM64 binaries, followed by
read-only hardware validation of their register contracts.

No Windows binary was installed or executed. Only archive extraction, PE metadata
inspection and ARM64 disassembly were performed. Vendor binaries remain outside
this repository. SHA-256 values below identify the acquired bytes; they are not
claims that Authenticode signatures have been independently verified.

The extracted contract, original-code emulator tests and two read-only hardware campaigns are documented in [the validation report](validation/README.md). The generated [contract JSON](vendor-contract.json) includes all register, CPUEB and IOCTL directory records.

## Confirmed packages and files

### MediaTek/NVIDIA MTEL driver: the direct match

ASUS publishes [MyASUS in WinRE for USB 1.0.0.521](https://dlcdnets.asus.com/pub/ASUS/nb/Image/CloudReinstallToolEXE/521/MyASUS_in_WinRE_For_USB_V1.0.0.521_1.exe)
for H7607BA and H7407BA in its [driver metadata](https://www.asus.com/support/webapi/ProductV2/GetPDDrivers?website=global&model=H7607BA&cpu=H7607BA&osid=52).
The acquired package contains the model-specific ARM64 recovery ISO
`A64W11_26H1_CR-ISO_H7607BA-217_02.00.iso` and `sources/boot.wim` inside it.

Its DriverStore contains:

```text
Windows/System32/DriverStore/FileRepository/
  nvmetelemetrykmd.inf_arm64_55ba1fed86df6be2/
    nvMeTelemetryKMD.inf
    nvMeTelemetryKMD.cat
    nvMeTelemetryKMD.sys
```

The INF explicitly binds **both `ACPI\NVDA8810` and `ACPI\NVDA8800`**, targets
`NTARM64.10.0...22000`, and declares `DriverVer=07/09/2026,2.2.0.0`.
The PE machine is `0xaa64` (ARM64), CompanyName is `Mediatek Inc.`, and
FileDescription is `MediaTek Driver for MeTelemetry`.

The binary contains the exact MTEL GUID
`12345678-1234-1234-1234-123456789abc` at file offset `0x2e870`, RVA `0x2fa70`.
Code at RVA `0x37bd4..0x37be0` loads that GUID. The driver imports
`MmMapIoSpace`; a call-site load of that import is at RVA `0x1a648`.
Its embedded PDB identity is `0C9DDA73D12F4A9B8AEDAD3C9FC9481F`, age 1.
The PDB path identifies `metelemetry_external/MeTelemetryKMD/ARM64/Release`.
Public availability of the corresponding PDB has not been established.

This is the direct implementation to investigate for MTEL `_DSM` resource
selection, directory parsing and raw telemetry acquisition. Binding both IDs
establishes that the Windows driver handles both devices; it does **not** prove
that their register layouts or measurement units are identical.

### NVIDIA platform controller: direct shared-memory evidence

The official [RTX Spark Game Ready Driver 617.42](https://www.nvidia.com/en-us/drivers/details/280415/)
provides this [Windows 11 ARM64 package](https://uk.download.nvidia.com/Windows/617.42/617.42-rtx-spark-notebook-win11-arm64-international-whql.exe).
Its ASUS display INF matches this machine exactly:
`PCI\VEN_10DE&DEV_2E03&SUBSYS_14841043`.

`NVPCF/nvpcf.inf` binds `ACPI\NVDA0820`, targets `NTarm64`, and declares
`DriverVer=08/30/2026,32.0.16.1679`. `NVPCF/nvpcf.sys` has that same file
version and PE machine `0xaa64`. The package's GPU driver is a different binary,
`nvlddmkm.sys` version `32.0.16.1742`; do not confuse its version with NVPCF's.

The following addresses are **RVAs for the exact NVPCF binary hashed below**;
the preferred image base is `0x140000000`.

| Evidence | RVA | Observed behavior |
|---|---|---|
| IAT entry | `0x3d0e8` | `ntoskrnl.exe!MmMapIoSpace` |
| Mapping setup | `0x5b98..0x5bb0` | Calls that import with physical address `0x1c238000`, length `0x814`, third argument 0 |
| Mapping stored | `0x5bbc` | Saves pointer at context offset `0xb50` |
| Offset directory | `0x3dc70` | 48 little-endian 32-bit offsets |
| Indexed reader | `0xcd28` | Checks index `< 0x30`, loads the table offset and copies from the mapped address |
| Indexed writer | `0xce68` | Checks index `< 0x30`, loads the table offset and copies to the mapped address |
| Update routine | `0xcfa8`, store at `0xd078` | Writes 32-bit value 1 to the mapped base |
| Cleanup | `0x6ed8..0x6ef0` | Unmaps length `0x814` and clears the saved pointer |

Decoded offset directory:

| Indices | Offsets, in index order |
|---|---|
| 0–7 | `0x100, 0x104, 0x108, 0x10c, 0x110, 0x114, 0x118, 0x11c` |
| 8–15 | `0x120, 0x124, 0x128, 0x12c, 0x130, 0x134, 0x138, 0x13c` |
| 16–23 | `0x140, 0x144, 0x148, 0x14c, 0x150, 0x154, 0x158, 0x15c` |
| 24–31 | `0x160, 0x164, 0x168, 0x16c, 0x170, 0x174, 0x178, 0x17c` |
| 32–39 | `0x800, 0x80c, 0x804, 0x810, 0x038, 0x808, 0x814, 0x30c` |
| 40–47 | `0x310, 0x324, 0x38c, 0x344, 0x380, 0x35c, 0x350, 0x374` |

Indices 32 and 33 match the DSDT-backed SoC and system power addresses already
validated on this P16. Several other offsets coincide with the DGX driver's
power, limit and energy offsets. That is a concrete lead for further analysis,
not sufficient proof of their N1X units, widths, validity or reset behavior.
Index 38 starts exactly at the requested mapping length (`0x814`), so the
mapping length alone must not be treated as a validated complete ABI size.

The NPCF GUID `36b49710-2483-11e7-9598-0800200c9a66` is present at RVA
`0x3db68`. Absence of the MTEL GUID from this binary did not exclude it from
SPBM access: its code uses a fixed physical mapping. String searches alone
would have missed this implementation.

### ASUS System Control Interface

The [ASUS System Control Interface package 3.2.68.0](https://dlcdnets.asus.com/pub/ASUS/nb/Image/Software/SoftwareandUtility/17801/ASUSSystemControlInterfacev3_ASUS_Z_V3.2.68.0_17801_2.exe)
contains ARM64 `AsusOptimization/AsusWmiAcpi.sys`, file version `2.1.73.0`.
Neither of the two GUIDs above was found as a contiguous binary GUID in that
file. It is not the primary lead now that the exact MTEL driver is available.

## Acquired file identities

| File | SHA-256 |
|---|---|
| NVIDIA 617.42 ARM64 installer | `425a75f54655ddcc8ee6859cec49bc431a17ef18094daaf59f205b159fb6e2bd` |
| `nvpcf.sys` 32.0.16.1679 | `530ea7f04474a1a95ba71d8397bbc3b48b210dd58fd7b7892256c705e1c36ef0` |
| ASUS WinRE 1.0.0.521 installer | `42c211bf3f14b226c5bfd04d2c6d8998997c84c90ef19f2db3839cae3d8fce1d` |
| `nvMeTelemetryKMD.sys` 2.2.0.0 | `7028cd64cdcced2382181cf29c7f9f6f21abf192412870c0e866d8e137cefced` |
| ASUS SCI 3.2.68.0 installer | `a616cf3e6c16d9acacd8f3659e6349e277d5ac2d08ebb1dbb7834aa4234504a9` |
| `AsusWmiAcpi.sys` 2.1.73.0 | `28ac29f7c99e2e6e41c2425deaee7160c6a29557ed6f82511437a4b795a15bb1` |

## Reproduce extraction and inspection

Use 7-Zip with BCJ2 support and innoextract. Install analysis-only Python
dependencies in a separate virtual environment using `tools/requirements.txt`.
They are not kernel-module dependencies.

For the NVIDIA package:

```sh
7zz x -onvidia 617.42-rtx-spark-notebook-win11-arm64-international-whql.exe 'NVPCF/*' 'Display.Driver/*.inf'
python tools/inspect-windows-pe.py nvidia/NVPCF/nvpcf.sys --code 0x5b98:0x24
python tools/inspect-windows-pe.py nvidia/NVPCF/nvpcf.sys --code 0xd06c:0x14
```

Decode the NVPCF offset table directly from the same binary:

```sh
python -c 'import pefile, struct; p = pefile.PE("nvidia/NVPCF/nvpcf.sys"); print([hex(v) for v in struct.unpack("<48I", p.get_data(0x3dc70, 192))])'
```

For ASUS WinRE, force the outer PE format: without `-tPE`, 7-Zip automatically
opens the nested executable, which hides the outer EXE resource:

```sh
7zz x -tPE -oouter MyASUS_in_WinRE_For_USB_V1.0.0.521_1.exe '.rsrc/EXE/102'
innoextract -e -d recovery outer/.rsrc/EXE/102
7zz x -oiso recovery/tmp/MyASUS_in_WinRE_For_USB_V1.0.0.521/A64W11_26H1_CR-ISO_H7607BA-217_02.00.iso sources/boot.wim
7zz x -odrivers iso/sources/boot.wim 'Windows/System32/DriverStore/FileRepository/nvmetelemetrykmd.inf_arm64_55ba1fed86df6be2/*'
python tools/inspect-windows-pe.py drivers/Windows/System32/DriverStore/FileRepository/nvmetelemetrykmd.inf_arm64_55ba1fed86df6be2/nvMeTelemetryKMD.sys --code 0x37bd4:0x10
```

The inspector reports hashes, file versions, PDB identities, GUID matches,
imports and optionally a bounded disassembly. It opens files as data and never
loads their code. RVAs and extraction paths above are version-specific.

Further extraction and read-only load validation are recorded in the linked
validation report. Exact control semantics, several field definitions and
long-duration behavior remain open. The installed Linux backend was not replaced.
