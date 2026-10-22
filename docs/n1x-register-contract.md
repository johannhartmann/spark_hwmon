# N1X register contract: confirmed interface and remaining gaps

Version `0.3.0.rtxspark.4` integrates the validated H7607BA.300 MMIO backend:
15 power readings, eight ACPI temperatures, four reduction-only power controls,
and unmodified raw status, energy and diagnostic words. Other matching N1X
systems retain ACPI sensor discovery; the MMIO extension is firmware-gated.
Full DGX parity is not claimed: exact energy calibration, physical PROCHOT
polarity and diagnostic units remain unresolved.

The sections below retain the initial firmware observations. Subsequent
[hardware validation](validation/open-gaps-research.md) and
[Windows reader execution](validation/windows-decompiler-analysis.md) establish
the register/control contracts now integrated. See the [README](../README.md)
for current installation and interface details.

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

## Integrated contract and remaining gaps

| Feature | Current implementation / remaining question |
|---|---|
| Power subdivisions and four EWMA values | Validated offsets and mW conversion integrated on H7607BA.300; accounting/filter details are not redefined |
| Four physical controllers | PL1, PL2, SysPL1, SysPL2 integrated; floor/ceiling and current EC default enforced; zero reset and owned-override cleanup |
| Five energy triplets | All 15 words exposed read-only and raw; exact scale, overflow arithmetic and reset/suspend accounting unresolved |
| Status | Raw `0x048` and `0x04c` exposed; no inferred PROCHOT alarm |
| Package temperature | ACPI decikelvin conversion retained; whole-degree `0x81c` available raw |
| `0x038`, `0x380..0x38c` | Read-only raw inspection; no control-bit or physical-unit interpretation |

The driver maps the vendor-established SPBM base directly only after exact
firmware gating, recognized MTEL schema, platform ID and range checks. It does
not use CPUEB table aliases as SPBM registers or relocate the DGX `_CRS` mapping.
Readback confirms an OS request was stored, while physical application remains
asynchronous. The current four write paths support reductions, not untested
increases beyond EC defaults. Earlier load experiments establish their physical
behavior; runtime integration checks temporarily reduce each limit by 1 W and
restore it without repeating the workloads.

## Sources and verification

- [DGX upstream implementation](https://github.com/antheas/spark_hwmon/blob/352c76e/spbm.c): named sensor-offset ABI used by NVDA8800.
- [Omarchy N1X thermal fix](https://github.com/omacom/omarchy-pkgs/blob/master/pkgbuilds/linux-omarchy-aarch64/1012-n1x-acpi-thermal-skip-power-telemetry.patch): PSYS/PSOC power readings masquerading as thermal zones on a Dell N1X platform; not a full SPBM register specification.
- [ASUS published driver metadata](https://www.asus.com/support/webapi/ProductV2/GetPDDrivers?website=global&model=H7607BA&cpu=H7607BA&osid=52): inspected for a matching vendor backend.

During the initial read-only investigation the installed module was
`0.3.0.rtxspark.3` with ten channels and no controls. That historical result is
superseded for the validated P16 by the `.4` implementation described above;
new runtime evidence is kept in `validation/n1x-mmio-integration.md`.
