# N1X register contract: confirmed interface and remaining gaps

Full DGX feature parity is **not implemented** for NVDA8810. The working N1X
backend exposes two power readings and eight temperatures on the validated ASUS
firmware. The directory returned by MTEL does not describe the missing sensor
registers. Hardware sharing a silicon design does not establish a firmware ABI.

The matching Windows vendor driver has now been obtained; see [Windows vendor driver evidence](windows-vendor-drivers.md) for the exact NVDA8810/NVDA8800 driver, versions, hashes and the NVPCF shared-memory access implementation. The observations below describe the initial firmware inspection; [the subsequent extraction and validation report](validation/README.md) establishes the CPUEB aliases, relative/absolute mappings and measured power/counter relationships.

## Firmware evidence

Examined platform: ASUS ProArt P16 H7607BA, BIOS H7607BA.300, ACPI device
`\_SB_.MTEL`, HID `NVDA8810`. The values below come from its decompiled DSDT;
they are observations for this firmware, not universal N1X constants.

MTEL uses UUID `12345678-1234-1234-1234-123456789abc`, revision 0.
Function 0 advertises functions 0–3. Function 1 returns `SPBM`, `SSPM`.
Function 2, sub-index 0, returns a flat directory:

| Key | Value |
|---|---|
| CFL | `0x0005ac00` |
| CPL | `0x0005a400` |
| CBL | `0x0005a600` |
| CCI | `0x0005c404` |
| CPI | `0x0005b400` |
| CTS0 | `0x0539a000` |
| CTS1 | `0x0b39a000` |

Function 3 returns `{0x05170000, 0x00060000}` for sub-index 0 and
`{0x311c0000, 0x100}` for sub-index 1. The apparent address/length pairs differ
from `_CRS`, whose Memory32Fixed descriptors advertise `0xffff0000` (length 1)
and `0x1c870200` (length `0x400`). Therefore the DGX procedure of locating a
resource by index and mapping a fixed 4 KiB region cannot be copied here.
`CTS0` and `CTS1` also do not fit inside the first function-3 region if treated
as relative offsets. The flat directory is not a list of hwmon sensor offsets.

A read-only inspection of the first function-3 region plus the five small
directory values succeeded using `/dev/mem` with read-only `mmap`. Ordinary
`pread` returned EFAULT on this machine. The inspection used aligned 32-bit
loads; it made no writes, changed no power profile and did not reload the driver.
The bytes have not established any new register's meaning or unit:

| Candidate block | Inspected address | Bytes inspected | First 32-bit word |
|---|---|---:|---|
| CPL | `0x051ca400` | 512 | `0xdefcdefc` |
| CBL | `0x051ca600` | 512 | `0x0000005a` |
| CFL | `0x051cac00` | 2048 | `0x00000000` |
| CPI | `0x051cb400` | 4096 | `0x00000000` |
| CCI | `0x051cc404` | 256 | `0x0000006c` |

These lengths are acquisition lengths, **not documented table sizes**.
The DSDT also returns `0x051cc404` from the power-management device's `PSHI`
method, together with `0x14`, `0xe8`, `0xd8`. That is a useful cross-reference,
not proof of a power sensor layout. Nonzero values, markers, or a value resembling
a wattage do not establish an ABI. A mostly zero block does not prove a disabled
feature. The original captures are retained locally, outside the repository;
unknown firmware contents are not redistributed as driver source or test fixtures.

## Proven ACPI accessors

`\_TZ.RREG` creates a four-byte SystemMemory region and reads its DWord.
The existing backend calls `_TMP` rather than mapping these addresses:

| Zone | DSDT address | Meaning | Raw unit |
|---|---|---|---|
| PSOC | `0x1c238800` | SoC power | mW, separately validated firmware quirk |
| PSYS | `0x1c23880c` | System power | mW, separately validated firmware quirk |
| TSOC | `0x1c238818` | SoC temperature | decikelvin |
| TS0E | `0x1c238820` | CPU E cluster 0 | decikelvin |
| TS0P | `0x1c238824` | CPU P cluster 0 | decikelvin |
| TS1E | `0x1c238828` | CPU E cluster 1 | decikelvin |
| TS1P | `0x1c23882c` | CPU P cluster 1 | decikelvin |
| TGPU | `0x1c238830` | GPU temperature | decikelvin |
| TUNC | `0x1c238834` | Uncore temperature | decikelvin |
| TDLA | `0x1c238838` | DLA temperature | decikelvin |

An independent read-only snapshot of `0x1c238800..0x1c23883f` confirmed readable
data at this separate location. Several intervening words are nonzero, but their
meaning is unknown. They must not be labelled as extra power channels or limits
based on proximity to the known fields. All these thermal zones use the same
`_CRT = 0x7fffffff` sentinel; that sentinel does not identify power units.

## Contract needed for full support

| DGX feature | N1X evidence still required |
|---|---|
| Additional power rails and EWMA averages | Named field mapping, units, validity, update cadence and availability |
| Four energy counters | Mapping, counter width, unit, rollover, reset and suspend behavior |
| PROCHOT / power-limit status | Field location, bit meanings and validity |
| Junction maximum | Definition and unit; a critical-trip sentinel cannot substitute for it |
| PL1 / PL2 / SYSPL1 / SYSPL2 | OS request and effective-value fields, bounds, ownership, firmware notification and acknowledgement, timeout and reset behavior |

The matching vendor implementation is now available: `nvMeTelemetryKMD.sys`
2.2.0.0 explicitly binds both MTEL hardware IDs, and `nvpcf.sys` 32.0.16.1679
contains shared-memory read, write and update routines. See the linked Windows
analysis for reproducible evidence. Their callers and field semantics still
need to be traced and checked against read-only captures under controlled CPU
and GPU loads before implementing controls.

Do not substitute the old DGX offsets, infer a common displacement from the two
known power readings, calculate software energy and present it as a firmware
counter, or enable power-limit writes before validating their N1X contract.
The Windows NVPCF implementation does contain an update store of 1 at the mapped
base; that establishes a vendor implementation to analyze, not validation of
all control fields, bounds or acknowledgement behavior.

## Sources and verification

- [DGX upstream implementation](https://github.com/antheas/spark_hwmon/blob/352c76e/spbm.c): named sensor-offset ABI used by NVDA8800.
- [Omarchy N1X thermal fix](https://github.com/omacom/omarchy-pkgs/blob/master/pkgbuilds/linux-omarchy-aarch64/1012-n1x-acpi-thermal-skip-power-telemetry.patch): PSYS/PSOC power readings masquerading as thermal zones on a Dell N1X platform; not a full SPBM register specification.
- [ASUS published driver metadata](https://www.asus.com/support/webapi/ProductV2/GetPDDrivers?website=global&model=H7607BA&cpu=H7607BA&osid=52): inspected for a matching vendor backend.

After the read-only investigation, the installed module still reported
`0.3.0.rtxspark.3`; `python3 tests/check-n1x.py --require-all` passed with all ten
channels, thermal-zone agreement and no power controls. No new sensor channels
or controls were enabled by this investigation.
