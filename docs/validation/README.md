# N1X vendor-contract extraction and validation

Validated on ASUS ProArt P16 H7607BA, BIOS H7607BA.300, kernel
`7.2.8-23-omarchy-p16-asus`, installed SPBM module `0.3.0.rtxspark.3`.
The ASUS platform profile remained `balanced`. No kernel/module replacement,
reboot, firmware writes or power-limit overrides were performed.

## What was extracted

[Machine-readable vendor contract](../vendor-contract.json) is generated from
the two exact Windows ARM64 binaries identified in [the acquisition report](../windows-vendor-drivers.md).
It contains all 48 NVPCF register offsets, eight raw parameter records, the MTEL
GUID, device-interface GUID, all four IOCTL records, and seven CPUEB directory
keys with their full aliases, context fields and mapping lengths.

The short directory keys are now explained by strings and code in the MTEL driver:

| Key | Full alias | Address on the tested firmware | Mapping length |
|---|---|---|---|
| CFL | `CPUEB_FASTDVFS_LOG_OFFSET` | SPBM base + `0x5ac00` | `0x800` |
| CPL | `CPUEB_PERFCNT_LOG_OFFSET` | SPBM base + `0x5a400` | `0x400` |
| CBL | `CPUEB_BPT_LOG_OFFSET` | SPBM base + `0x5a600` | `0x400` |
| CCI | `CPUEB_CPPC_INTERFACE_OFFSET` | SPBM base + `0x5c404` | `0x1000` |
| CPI | `CPUEB_PL_INTERFACE_OFFSET` | SPBM base + `0x5b400` | `0x1000` |
| CTS0 | `CPUEB_TJPID_SLAVE0_OFFSET` | **absolute** `0x0539a000` | `0x400` |
| CTS1 | `CPUEB_TJPID_SLAVE1_OFFSET` | **absolute** `0x0b39a000` | `0x400` |

Here the firmware's first function-3 base is `0x05170000`. This MTEL resource
is distinct from NVPCF's telemetry/control mapping at `0x1c238000`. The original Windows
mapping routine at RVA `0x13b0` was executed in emulation with this directory;
all seven address calculations and lengths matched. In particular, the CTS
values must not be added to the SPBM base. These tables provide CPUEB diagnostic
interfaces, not a named catalogue of the missing hwmon power rails.

The MTEL field parser at RVA `0x1a6c8` accepts a cursor pointing at an ACPI string
argument's data, compares the requested key, reads the following 32-bit value,
and advances to the next pair. The caller tries short keys and then full aliases.
Both spellings for all seven keys, wrong-key behavior and null arguments were
tested using the original parser bytes. This does not validate arbitrary malformed
ACPI output lengths or the entire Windows device stack.

The four MTEL IOCTL records at RVA `0x33720` have the following static layout:

| Code | Minimum input | Minimum output | Callback RVA |
|---|---:|---:|---|
| `0x222004` | 12 | 0 | `0x8530` |
| `0x222008` | 16 | 0 | `0x8870` |
| `0x22200c` | 4 | 12 | `0x8bd0` |
| `0x222010` | 0 | 16 | `0x8ea0` |

Device-interface GUID: `41a92821-d71e-4d9d-979c-fcb82d9158d8`.
The IOCTL-record structure was cross-checked against Microsoft's
[DMF IoctlHandler definition](https://github.com/microsoft/DMF/blob/master/Dmf/Modules.Library/Dmf_IoctlHandler.h).
The INF's device security descriptor grants access to administrators and SYSTEM.
The full IOCTL dispatchers were not exercised against a Windows kernel.

## Tests against original Windows machine code

The test harness loads the **hash-pinned** ARM64 PE images into Unicorn's
emulated RAM. It does not load Windows drivers into Linux and never opens a
physical device. Real vendor helper, table and copy instructions execute.
NVPCF's WDF context lookup and CFG dispatch are stubbed. MTEL additionally stubs
kernel `strcmp` and `MmMapIoSpace`; the latter only records address/length pairs.

Covered cases:

- all 48 indexed reads and all 48 indexed writes, with exact emulated addresses;
- a separate 32-bit update store of 1 at offset zero;
- invalid indices, missing mappings and WDF contexts;
- zero-length requests, null write buffers and a 12-byte record read;
- an overlong copy hitting an unmapped emulation guard page;
- all seven short/full MTEL key pairs, wrong keys and null arguments;
- all seven MTEL address/length calculations, including absolute CTS addresses;
- refusal of an unknown binary hash.

Two implementation details matter for a Linux port. The vendor's indexed copy
helper checks the index but does **not** bound the length to the mapping or field.
Index 38 also starts at `0x814`, exactly at the vendor's requested mapping
length; a four-byte read needs bytes through `0x817`. The emulator and passive
capture use a 4 KiB page. A Linux port must not copy the undersized `0x814`
mapping length blindly. Also, its four-byte copies use individual byte accesses
in this build. The update
helper is a separate store and does not wait for acknowledgement. A Linux backend
must supply its own bounds, appropriate I/O access widths, validated control
semantics and error handling; importing the vendor table alone is insufficient.

## Hardware measurements

Each capture contains **550 samples over 55 seconds**, at 100 ms target spacing.
All physical accesses were read-only and used aligned 32-bit loads through a
`PROT_READ` mapping. The capture tool refuses a different DMI identity or BIOS.
It reads the 48 vendor offsets, adjacent candidate-counter words and DSDT-backed
temperatures. The second capture additionally probes the legacy DGX power
window `0x300..0x33c` inside the same shared-memory page.

Workload phases were baseline, eight CPU SHA-256 worker processes for 12 seconds,
recovery, repeated Qwen3-4B Q4_K_M CUDA inference, then cooldown. The existing
llama.cpp server was configured with `--n-gpu-layers 999`. It generated 896 tokens
in seven requests in the first run and 768 tokens in six requests in the second.
Baseline includes the desktop and already running services; this is not a
calibrated idle-power benchmark.

Mean raw power-window values in the second capture, interpreted as mW for this
comparison and shown in W. Labels are candidates inherited from the DGX map;
response to these workloads supports some roles but does not prove every rail's
physical accounting boundary:

| Offset | Candidate | Baseline | CPU phase | CUDA phase |
|---|---|---:|---:|---:|
| `0x300` | System | 59.83 | 109.70 | 109.89 |
| `0x304` | Package | 27.15 | 67.31 | 60.96 |
| `0x308` | CPU + GPU | 17.24 | 57.17 | 41.06 |
| `0x30c` | CPU P | 4.83 | 44.66 | 16.25 |
| `0x310` | CPU E | 0.39 | 0.85 | 0.46 |
| `0x314` | VCORE | 5.13 | 5.26 | 11.62 |
| `0x31c` | DC input | 59.51 | 109.09 | 109.44 |
| `0x324` | GPU | 11.07 | 10.65 | 23.40 |
| `0x338` | Pre-regulator | 4.96 | 5.08 | 9.59 |

Offsets `0x318`, `0x320`, `0x328`, `0x32c`, `0x330`, `0x334`, and `0x33c`
stayed zero during these workloads. That does not establish absent hardware:
for example, no DLA/NPU workload was run.

The two power values currently exposed through ACPI, `0x800` and `0x80c`,
responded slowly to load changes. They must not be treated as instantaneous
energy-integration references. `0x804` tracked package power much more promptly;
it was approximately 0.5 W above the legacy `0x304` reading in this capture.
The exact filter definitions and that offset are not yet established.

Counter deltas were compared to trapezoid-integrated power using actual sample
timestamps. Assuming mJ counters and mW power, the ratio should approach 1:

| Counter / comparison | Result across phases in both runs |
|---|---|
| Package `0x344` / power `0x804` | Within 3% of 1 |
| CPU P `0x35c` / power `0x30c` | Within 15% of 1 |
| GPU `0x374` / power `0x324` | Within 10% of 1 |
| CPU E `0x350` / power `0x310` | **Disagrees**, ratios about 1.6–2.8 |

These thresholds are checked by tests against the committed captures. All four
candidate energy values increased without decreases during the short runs;
their next two 32-bit words stayed zero. That does not prove a 32-bit versus
64-bit firmware counter or hardware rollover behavior. A roughly 0.5 W additive
term reduces the E-core mismatch, but no correction has been applied: its cause
and the precise domain definition still need to be established.

Direct reads agreed with the installed ACPI backend within 0.4 C for temperatures
and 10 mW for power in these sequential samples. Peak recorded SoC temperatures
were 78.65 C and 80.75 C. The loaded module continued to expose all ten existing
channels after the experiments.

All eight OS override words (`0x100..0x11c`) remained zero in both captures.
The other blocks contained the following values or ranges across both runs:

| Block | Observed values in index order |
|---|---|
| `0x120..0x12c` | `55000, 70000, 0, 0` |
| `0x130..0x13c` | `126000..131000, 138000..145000, 155000..162000, 173000..180000` |
| `0x140..0x15c` | all zero |
| `0x160..0x16c` | `55000, 70000, 80000, 0` |
| `0x170..0x17c` | same four ranges as `0x130..0x13c` |

The trailing values changed autonomously while the OS override words stayed zero.
The meanings of all three blocks have not been established for N1X. They must
not simply be labelled as minimum/maximum/effective limits from their position.
`0x038` stayed at 1019; `0x38c` and the words at `0x380..0x388` varied. Their
status/clock/telemetry meanings remain unresolved and they are not exposed as
boolean throttle flags or additional energy sensors.

Validation outcome: **39 tests passed with the vendor binaries available**;
`make modules W=1` and `tests/check-n1x.py --require-all` passed. Without vendor
files, 15 original-binary tests skip and the 24 portable/recorded tests remain.

## Reproduction

The [research follow-up](open-gaps-research.md) establishes E-core counter
attribution with selective affinity loads, identifies the actual status fields,
and physically validates all four power controllers and their reset behavior.
The complete evidence now contains 26,434 samples and 51 tests (18 require the
pinned vendor binaries). Firmware energy calibration, PROCHOT polarity and
internal diagnostic encodings remain unproven. The installed driver is unchanged.

Install analysis dependencies in a virtual environment, acquire/extract the
vendor files using the acquisition report, then run from the repository root:

```sh
python -m pip install -r tools/requirements.txt
SPBM_VENDOR_DIR=/path/to/vendor-windows python -m unittest discover -s tests -v
python tools/vendor_contract.py /path/to/nvpcf.sys /path/to/nvMeTelemetryKMD.sys
python tools/analyze-n1x.py docs/validation/legacy-load-capture.jsonl.gz
make modules W=1
python3 tests/check-n1x.py --require-all
```

`SPBM_VENDOR_DIR` uses the acquisition directory layout: it contains
`nvidia-617.42-extracted/NVPCF/nvpcf.sys` and the extracted MTEL file below
`asus-winre-drivers/`. Without that environment variable the proprietary-binary
tests explicitly skip; portable helper, analysis and recorded-hardware tests run.

Raw captures are compressed JSONL. `manifest.json` contains both compressed and
uncompressed SHA-256 values. Reports can be regenerated from the captures.
`*-events.json` records workload transitions and request counts.

For a new passive capture on this exact firmware:

```sh
sudo python3 tools/capture-n1x.py capture.jsonl --duration 55
python3 tools/analyze-n1x.py capture.jsonl
```

To repeat the CPU/CUDA phases, first ensure the existing Qwen3-4B CUDA server is
available on localhost:8080 as `p16-local`. Prepare a fresh phase file and start
capture in one terminal:

```sh
printf idle > phase.txt
sudo python3 tools/capture-n1x.py capture.jsonl --duration 55 --phase-file phase.txt
```

Immediately run this in a second terminal as the ordinary user:

```sh
python3 tools/n1x-workload.py capture.jsonl phase.txt events.json
```

The workload script reproduces the eight CPU workers and repeated inference
requests; its event output records actual transitions and generated token counts.
Use fresh output paths for each run. Hardware-capture identity checks still apply.

A phase file can annotate a capture with workload names. This option changes only
sample labels; the capture tool never launches workloads or writes device state.

## Remaining validation gaps

- Physical power-limit writes, firmware acknowledgement and restore semantics.
- Exact N1X units/accounting for the E-core energy comparison and remaining rails.
- Counter width, hardware wrap, reset and suspend/resume behavior.
- Status/clock words and detailed CPUEB log/power-interface record formats.
- Full Windows IOCTL behavior and cross-machine/BIOS compatibility.
- Production discovery of long-key directory variants: the current Linux schema
  recognizer accepts the five short keys; the Windows aliases are extracted and
  tested here but have not been added to the installed Linux driver.

The installed Linux driver remains the existing read-only backend. These results
are a tested basis for further implementation, not a claim of full DGX feature
parity or universal RTX Spark hardware validation.
