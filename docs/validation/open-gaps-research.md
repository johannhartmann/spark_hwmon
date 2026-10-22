# N1X energy attribution, status and physical power control

Validated on 2026-10-22: ASUS ProArt P16 H7607BA, BIOS H7607BA.300,
kernel 7.2.8-23-omarchy-p16-asus. The installed module remains
`0.3.0.rtxspark.3`; these research results have not yet been integrated into
its ACPI-only backend. No boot configuration or firmware was changed.

## Results

| Question | Result |
|---|---|
| Does energy counter `0x350` belong to E cores? | Selective, repeated E/P loads support E-domain attribution. It disagrees systematically with integrated instantaneous E power; no calibration correction is justified. |
| Where are the actual status fields? | `pl_level` is `0x048`, raw `prochot` is `0x04c`, whole-degree package temperature is `0x81c`. `0x038` was a mistaken status candidate. |
| Does physical control work? | PL1, PL2, SysPL1 and SysPL2 were each made the active controller and measured under load. Zero restores EC limits. |
| Is every internal word decoded? | No. `0x038`, packed `0x380..0x388`, the exact `0x38c` physical unit and PROCHOT polarity remain unproven. They must not be exposed as invented alarms or calibrated sensors. |

## E-core energy attribution

A 110-second capture at 73 ms intervals contains 1,507 samples. Thirty worker
processes set and verify individual CPU affinity before hashing. Their reports
are retained in `affinity-events.json`. MIDR identifies Cortex-A725 (`0xd87`) on
CPUs 0–4 and 10–14, and Cortex-X925 (`0xd85`) on CPUs 5–9 and 15–19. These part
numbers are specified by [Arm](https://documentation-service.arm.com/static/665741bb876c8d213b78610b)
and [LLVM's CPU identification code](https://github.com/llvm/llvm-project/blob/main/llvm/lib/TargetParser/Host.cpp).

| Phase | E power `0x310` | E energy delta/time `0x350` | P energy delta/time `0x35c` |
|---|---:|---:|---:|
| Recovery after E load | 0.247 W | 0.665 W | 4.400 W |
| Ten E cores loaded | 4.275 W | 5.019 W | 9.301 W |
| Ten P cores loaded | 0.959 W | 1.462 W | 44.056 W |
| Ten E cores loaded again | 4.271 W | 5.038 W | 8.323 W |

Selective excitation and repeatability support E-domain assignment; the earlier
un-pinned experiment could not establish it. This does not establish absolute
physical calibration, exact counter width, wrap or suspend/reset semantics.
Counter-derived values above use the candidate mJ conversion, supported by the
other domain comparisons in [the earlier validation](README.md).

The discrepancy is not a constant unit multiplier. In the earlier complete
capture, counter-derived minus integrated power averaged approximately +257 mW
(package), +408 mW (P), +453 mW (E), and +420 mW (GPU). The affinity experiment's
E-load difference is about +0.75 W, versus +0.42 W during recovery. Whole-watt
ceiling integration improves some loaded phases but overestimates idle E energy.
Neither that model nor an added 500 mW baseline is a validated firmware formula.

Independent [GN100 observations in NVIDIA's forum](https://forums.developer.nvidia.com/t/gb10-grace-cpu-energy-telemetry-full-audit-paper-follow-up-to-closed-thread-360631/371614)
also report differing instantaneous and counter-derived E power. More usefully,
an independent [DGX experiment with published raw evidence](https://github.com/aien-dev/omega-mv/blob/a8ffd2b912c84197d08f963b05f9c7d8b30a3f8a/research/m15/spbm/runs/preflight-20260928-03/summary.json)
reports roughly 1.50–1.67 W instantaneous E power and 2.02–2.22 W counter-derived
power during E load. This corroborates the disagreement, not an exact correction
or an identical N1X firmware algorithm. Keep firmware energy and instantaneous
power as separate measurements; do not silently manufacture agreement.

## Register identities and status

A [published DGX firmware dump](https://github.com/aien-dev/omega-mv/blob/a8ffd2b912c84197d08f963b05f9c7d8b30a3f8a/research/m15/spbm/runs/preflight-20260928-03/DSDT.dat)
contains 207 SPBM key/offset pairs. `dgx-directory-crosscheck.json` records their
names, offsets, provenance and the binary DSDT hash; the proprietary dump is not
redistributed here. Its CPUEB addresses agree with this N1X DSDT. The Windows
NVPCF access table and local interventions independently support the slots below.
DGX names alone are not proof of N1X semantics.

| Addresses | Meaning and local validation |
|---|---|
| `0x100..0x11c` | OS overrides; explicit writes change the corresponding effective limits |
| `0x120..0x13c` | EC limits; selected values remain in place during override and take effect after reset |
| `0x140..0x15c` | UEFI limits in the canonical directory; all zero locally |
| `0x160..0x17c` | Effective limits; follow overrides and restore to EC values |
| `0x708/0x70c`, `0x718/0x71c` | PL1/PL2 floor/ceiling: 100 / 160000 mW |
| `0x738/0x73c`, `0x748/0x74c` | SysPL1/SysPL2 floor/ceiling: 100 / 250000 mW |
| `0x048` | Active controller, observed `0x01` PL1, `0x02` PL2, `0x08` SysPL1, `0x10` SysPL2 |
| `0x04c` | Raw PROCHOT field; always 1 in our captures; polarity/alarm semantics unvalidated |
| `0x81c` | Whole-degree package temperature: for example 63 beside 3368 dK (~63.65 C) |

The controller values are bit-coded identifiers, not consecutive level numbers.
Unobserved encodings must not be assigned solely by extrapolation. Independent
[DGX operator measurements](https://github.com/vtemian/sparkup/blob/main/roles/spbm/README.md)
also find that `prochot` stays at 1 during a power-limited workload; nonzero must
not automatically be interpreted as an asserted thermal alarm. No thermal
protection was disabled and no thermal trip was deliberately induced here.

`0x038` remained 1019 (`0x3fb`). It is neither canonical `pl_level` nor `prochot`.
The captures reveal near-exact encoding relationships:

* `0x38c = byte1(0x380) * 5 + 245` in 1,343 of 1,507 affinity samples.
* `0x388 = floor(byte0(0x380) * 100000 / 170)` in 1,219 of those samples.

Small discrepancies are consistent with sequential reads during firmware updates.
These fits do not prove voltage, frequency, utilization or current units. The
30-second `status-capture.jsonl.gz` includes `/proc/stat` and CPU frequency reads;
the frequency reads sometimes exceed configured maxima, so they cannot be used
as an independent calibration reference. The packed words are not monotonically
increasing energy counters.

## Physical power regulation

Normal-user, affinity-pinned P-core workers supplied CPU load. System tests also
used the existing CUDA Qwen server, with successful request/token counts recorded.
The final five seconds of the reduced phases measured:

| Experiment | Overrides | Active controller | Fast measured power |
|---|---|---|---:|
| `cap-experiment` | PL1 35 W | `0x01` | Package `0x804`: 35.028 W |
| `package-cap-experiment` | PL1 35 W, PL2 40 W | `0x02` | Package `0x804`: 40.893 W |
| `system-cap-experiment` | SysPL1 75 W, SysPL2 85 W | `0x10` | System `0x814`: 85.412 W |
| `sustained-system-cap-experiment` | SysPL1 60 W only | `0x08` | System `0x814`: 59.972 W |

These are sampled intervention results, not a promise of zero transient overshoot.
Package power after restoring the first test was 55.096 W. All tested overrides
returned to zero, and effective limits returned to their then-current EC values.
EC system defaults change autonomously; restoring an old copied default would be
incorrect. Resetting the OS override lets firmware supply the current default.

The 80-second limited phase in `system-long-cap-experiment` still selected
SysPL2. The isolated 60 W SysPL1 experiment selected SysPL1 after roughly 40 seconds
of the override, and its final window reached the target. Its `0x62c` PID output
fell from 250000 to below 10000 while the status changed to `0x08`. The canonical
SysPL1 time parameter at `0x23c` is 60000, compared with 5000 for SysPL2. The exact
internal PID equation is not decoded. An immediate effective-limit readback
therefore does not establish immediate physical limiting.

`tools/n1x-cap-experiment.py` permits only fixed reductions on this exact DMI/BIOS,
checks initial bounds and the absence of existing OS overrides, aborts on invalid
or excessive temperatures, and restores through `finally` plus an independent
forked watchdog. Only selected OS slots and update offset zero are written. No
PID coefficients, thermal trips, EC limits or boot settings are changed.
`tools/n1x-cap-workload.py` runs the corresponding unprivileged CPU/CUDA workload.
These are explicit research tools, not installed services.

## Windows instruction-level contract

All RVAs refer to NVIDIA 617.42's ARM64 `nvpcf.sys` 32.0.16.1679, SHA-256
`530ea7f04474a1a95ba71d8397bbc3b48b210dd58fd7b7892256c705e1c36ef0`.
Acquisition is documented in [the vendor report](../windows-vendor-drivers.md).

The descriptor accessor at RVA `0x216d0` takes two 64-bit descriptor halves in
`x0`/`x1` and a pointer in `x2`. Byte 9 selects the access kind: 5 is SPBM.
Byte 10 is copy length. Byte 11 selects direction: 0 reads; 2 writes. The SPBM
branch begins at `0x21880`. Read clears the pointed-to result, then calls the
indexed reader (`0xcd28`). Write takes the index from the pointed-to value and
data from the first descriptor word, calls writer (`0xce68`), then update
(`0xcfa8`) only on success. Update stores 32-bit 1 at shared-memory offset zero.
Direction 1 returns `0x56`; index 48 returns `0x3b`; neither commits a write.

Original instructions execute in Unicorn RAM for read, all eight override slots,
and failure cases. Four-byte data writes use four byte stores, followed by the
32-bit update store. This accessor does not poll an acknowledgement; that does
not prove there is no acknowledgement mechanism elsewhere in firmware.

| ID | OS write | Getter type 6: EC | Getter type 8: UEFI |
|---|---|---|---|
| `0x5001` | `0x100` PL1 | `0x120` | `0x140` |
| `0x5002` | `0x104` PL2 | `0x124` | `0x144` |
| `0x5003` | `0x108` PL3 | `0x128` | `0x148` |
| `0x5004` | `0x10c` PL4 | `0x12c` | `0x14c` |
| `0x500a` | `0x110` SysPL1 | `0x130` | `0x150` |
| `0x500b` | `0x114` SysPL2 | `0x134` | `0x154` |
| `0x500c` | `0x118` SysPL3 | `0x138` | `0x158` |
| `0x500d` | `0x11c` SysPL4 | `0x13c` | `0x15c` |

The getter's signed-32-bit jump table is at `0xc7d4`, relative to `0xc598` in
instruction units. The setter's signed-byte table is at `0xcce0`, relative to
itself in instruction units. IDs `0x5005..0x5009` select failure. The setter clears
the local value for request types 6/8 at `0xcbec`, and calls update once after its
loop at `0xcca4`. These dispatcher mappings are static control-flow findings;
the complete high-level dispatchers have not been emulated. The local experiments
validate zero/reset for the four tested limits. PL3/4 writes were not attempted.

## Evidence, verification and remaining specification gaps

Compressed JSONL captures and workload events are committed beside this report.
`manifest.json` contains compressed/uncompressed SHA-256 hashes and sample counts.
The tests verify hashes, selective E/P response, all four active controllers,
measured limiting, restoration and original Windows-helper instruction behavior.
The final passive capture independently checks all eight OS override words are
zero and the four tested effective limits match EC defaults.

The energy-counter bias, raw PROCHOT polarity and internal diagnostic fields still
need a vendor formula, decoded firmware consumer/producer or an independent
physical reference. They are not silently declared calibrated or decoded.
Additional statically inspected recovery drivers (`nvpep.sys` 2.6.0.0,
`nvSCP.sys` 2.17.0.0, `nvsrootmbx.sys` 2.10.0.0) provided no named SPBM fields.
ASUS's BIOS API returned no model firmware package; Microsoft Update Catalog
returned no result for firmware GUID `97686c57-e102-5ecf-ae23-27647f24f0ca`.
Those acquisition failures do not prove every possible source is unavailable.

## Reproduction

The cap experiment serializes instances with a runtime lock; do not run another
power-control writer concurrently. Start the capture and its workload promptly
in separate terminals, with fresh output paths. For the isolated SysPL1 test:

```sh
# Terminal 1, from this repository:
sudo python3 tools/n1x-cap-experiment.py /tmp/syspl1-test.jsonl --case sustained-system --long-window
# Terminal 2, as the normal desktop user:
python3 tools/n1x-cap-workload.py /tmp/syspl1-test.jsonl --gpu --long
```

For the affinity experiment, use `capture-n1x.py --duration 110 --interval .073
--phase-file PHASE`, and `n1x-affinity-workload.py CAPTURE PHASE EVENTS` as the
ordinary user. This performs E/P/E phases with verified affinity and does not
write any power controls. See each tool's `--help`.

Run all offline evidence and original-vendor-instruction tests as documented in
the [validation README](README.md). Without the pinned vendor artifacts, their
18 instruction/static-contract tests explicitly skip; recorded-hardware and
portable tests still run. Recomputing a recorded result is not a new hardware
experiment, and the evidence applies only to the tested BIOS.
