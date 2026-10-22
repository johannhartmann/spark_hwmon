# Windows consumer analysis

Analysis on 2026-10-22 used Ghidra 12.2 PUBLIC with its native Linux AArch64
decompiler and radare2 6.1.4. All execution described below is in Unicorn RAM;
no Windows driver was loaded and no hardware controls were written.

## NVPCF sampler

The input is NVIDIA 617.42's `NVPCF/nvpcf.sys`, SHA-256
`530ea7f04474a1a95ba71d8397bbc3b48b210dd58fd7b7892256c705e1c36ef0`.
Ghidra decompiled 595 functions. RVAs below are relative to image base
`0x140000000`; radare2 independently identifies calls to the indexed helpers.

| RVA | Observed role |
|---|---|
| `0x205f0` | Client configuration dispatcher; registers the DPC sampler |
| `0x218f8` | Expands client-supplied packed controls into 16-byte descriptors |
| `0x21218` | Validates descriptor bus, direction, tag and copy length |
| `0x1fc10` | Reads registered descriptors and returns raw values/status |
| `0x21f48` | Reads sequential descriptors into output slots |
| `0x22100` | DPC sampler, including SPBM read/write dispatch |
| `0x223c0` | Sampling worker, copying results to a shared ring buffer |

Packed descriptor bits 1:0 become the tag byte; bits 5:2 the bus byte;
bits 9:6 the copy-length byte; bits 12:10 the direction byte. Expanded bus 5
selects SPBM and direction 0 reads, while direction 2 writes. Paired write
records carry the index and payload separately. The inspected paths transport
raw values; they do not establish an energy calibration formula.

For NVIDIA CPU type 2, the original validator accepts a direction-2/tag-0
SPBM descriptor only for index 36, which the pinned offset table maps to
`0x038`. A tag-1 write descriptor represents its paired payload. This makes
`0x038` a control-write destination in this API; it does **not** identify its
individual bits, their polarity, or which changes would be appropriate.

The validator accepts a read descriptor with index 48 even though the later
indexed helper rejects it. It rejects copy lengths above 7. Validation and
actual register access therefore have different checks. The opt-in test
`test_original_sampler_validator_spbm_control_contract` executes seven cases
from the original machine code and asserts zero MMIO reads/writes.

## FrameView lead

The same installer includes `FrameViewSDK/SDK/Public_Release/FvSDK.h`:
SHA-256 `7291ea3a6b538e4136fe5acbd3a45f5b512b1aa56bc6a99fb83cf793ce446640`.
Its `eCPUPwr` metric ID is `0xbb272534`. `CPUPwr_v1` specifies separate
double-precision E-core and P-core power fields in watts for Windows on ARM.
This documents an output contract, not the energy-counter conversion.

`FrameViewSDK/bin/FvSDK_ARM64.dll`, SHA-256
`13143a08a97ca102a494f06978b20edb63cb9236750415c64aa1d1346117aeba`,
contains this ID in its supported-metric and dispatch metadata. Its bundled
ARM64 PDB contains names including `ECoreMilliWatts`, `PCoreMilliWatts`,
`mCpuECorePwr` and `mCpuPCorePwr`. Following the corresponding producer is a
more specific path than searching generic kernel register-copy helpers.

Loading that PDB resolves `FvSDK::FvClientCtx::SampleData` at RVA `0x1dc88`.
Its `FV_MESSAGEBUS_MESSAGE_SYSTEM_DATA_TYPE_N1X_SOC` branch copies the message's
`ECoreMilliWatts` and `PCoreMilliWatts` fields into cached state. The output path
multiplies those cached integers by **0.001** into `mECorePwr` and `mPCorePwr`.
The binary double at RVA `0x20198` is exactly the C double representation of
0.001. The SDK only emits this power sample when both cached values are positive;
the WoA package-power field is zero. There is no energy-counter correction in
this conversion. The N1X message producer remains to be followed: this consumer
does not establish which SPBM registers generated its input values, nor how
firmware accumulates energy. Some unrelated PDB type reconstructions generate
alignment warnings, so inferred layouts need instruction-level confirmation.

The collector plugin named `SystemDataCollectorsContainerPlugin_ARM64.dll`
is ARM64EC: its PE machine field is AMD64, but its CHPE code map identifies
AArch64 main code and x64 thunks. Import main code into Ghidra with
`-processor AARCH64:LE:64:v8A -cspec windows`; do not interpret it wholesale as
x86-64. Some thunk functions fail decompilation and require separate handling.

## MTEL platform tables and complete reader execution

Further analysis uses `nvMeTelemetryKMD.sys` 2.2.0.0, SHA-256
`7028cd64cdcced2382181cf29c7f9f6f21abf192412870c0e866d8e137cefced`.
The selector at RVA `0x38668` chooses one of three static platform templates;
the copier at `0x387b0` rearranges that template into the device context.
**Context offsets must not be inferred from the order of the DGX ACPI keys.**
The actual copier performs explicit reordering and includes additional fields.
`MtelMachine.platform_layout()` executes both routines from the pinned binary.

All three templates select SPBM base `0x1c238000`. Platform 1 requests `0x800`
bytes, platforms 2 and 3 request `0x1000`. The local N1X DSDT's `PLID` returns 2;
this agrees with platform 2, although emulating a template is not a complete
Windows device-initialization test. Key extracted context members are:

| Device-context member | Register offset |
|---|---|
| `0x1a0`, `0x1a4` | `0x048` controller status, `0x04c` PROCHOT |
| `0x1a8`, `0x1ac` | `0x008` PID winner, `0x00c` PID-winner lock |
| `0x1b0..0x1e8`, stride 4 | `0x344..0x37c`, stride 4: five energy triplets |

The original status reader at RVA `0x134e0` copies the two 32-bit status words
directly into its output. Emulation with PROCHOT inputs 0, 1, 2, `0x80000000`
and `0xffffffff` returns each unchanged. Its only MMIO reads are `0x048` and
`0x04c`; it performs no MMIO writes. Thus **this Windows API does not normalize
PROCHOT to a Boolean or invert it**. That establishes the transport semantics,
not whether raw 1 means asserted, deasserted, enabled or something else in
firmware. The driver's raw reader cannot settle physical polarity.

The original energy reader at RVA `0x138a0` reads all 15 consecutive 32-bit
words from `0x344` through `0x37c` into 15 separate output slots. Emulation
using distinct values near `UINT32_MAX` confirms exact preservation, including
the overflow and clear words, with no MMIO writes. **It neither combines them
into wider counters nor applies a scale, baseline, rounding rule or per-domain
correction.** A 32-bit Windows transfer does not prove the physical accumulator
width or the overflow word's arithmetic meaning. This also does not establish
the firmware's absolute energy unit or its E-core integration formula.

The original power reader at RVA `0x131d0` first reads all 16 words
`0x300..0x33c`, then zeros output slots 7, 8, 10, 11, 12 and 15. The remaining
slots, including E and P power, are returned unchanged. Tests distinguish
actual reads from those overwritten outputs. Zero in this Windows structure
therefore need not mean zero at the corresponding firmware address; it does
not establish that the physical channel is absent.

None of the three extracted MTEL layouts registers `0x038`, `0x380`, `0x384`,
`0x388` or `0x38c`. NVPCF independently exposes `0x380` and `0x38c` as raw
indexed samples, but that access path provides no physical-unit decoding.
The numerical fits in the hardware captures remain hypotheses about encoding,
not evidence that these words are voltage/current/frequency sensors.

Four additional opt-in tests execute these original routines, verify the
platform layouts and raw return values, and record the precise emulated MMIO
accesses. They deliberately do not trigger a physical overflow or thermal trip.

## Wider consumer search and remaining boundary

[The inventory](windows-consumer-inventory.json) pins six additional user-mode
artifacts and records their Ghidra export counts: the native NVAPI implementation,
DGX telemetry plugin, FrameView collector, aggregator, capture executable and
service. This is an analysis inventory, **not proof that every decompiled
function is correct or every possible consumer has been traced**. The DGX
plugin's `SPBM_TRACKER` string occurs among reset-reason enum names; that name
alone does not identify a power-calibration routine. The
[public NVAPI interface list](https://github.com/NVIDIA/nvapi/blob/main/nvapi_interface.h)
does not provide a named N1X energy/PROCHOT contract.

The concrete remaining target is the producer of the SPBM words, or a consumer
that assigns their semantics. Neither the executed Windows register readers
nor the decoded SDK watt conversion supplies the missing E-core accumulation
formula, PROCHOT interpretation or packed diagnostic units. A usable SSPM/SPBM
firmware image has not been extracted from these Windows packages. The CPUEB
SRAM snapshot acquired earlier is not established as that firmware image.
Continuing requires identifying and extracting the relevant firmware payload
or locating another typed consumer; arbitrary SRAM bytes must not be assumed
to be executable code. There is no evidence-backed calibration or polarity
patch to apply from these findings alone.

## Reproduction

Keep acquired binaries, Ghidra projects and generated proprietary decompiler
output outside the repository. `tools/ghidra/ExportAnalysis.java` exports
function bodies and a JSON call inventory to an explicit local directory.
For an imported native ARM64 binary:

```sh
analyzeHeadless PROJECT_DIRECTORY PROJECT_NAME \
  -import /path/to/nvpcf.sys -analysisTimeoutPerFile 180 -max-cpu 2 \
  -scriptPath "$PWD/tools/ghidra" \
  -postScript ExportAnalysis.java /path/outside/repository/nvpcf-analysis
```

Use the supported JDK for the installed Ghidra release. On this machine the
project directory had to avoid hidden path components. Run the pinned vendor
tests using `SPBM_VENDOR_DIR` as described in the validation README.

For the SDK, supply `-preScript SetLocalPdb.java /path/to/FvSDK_ARM64.pdb`
before normal analysis. The bundled DLL's RSDS GUID is
`b85e5f87-53c3-401e-87de-f981b822ed82`, age 2. Let the PDB analyzer check the
match; do not force a mismatched symbol file or use `-noanalysis` when loading
symbols this way.

Exact energy calibration, PROCHOT polarity and packed diagnostic units remain
unresolved. This analysis does not justify changing their Linux sensor labels
or introducing a numerical correction.
