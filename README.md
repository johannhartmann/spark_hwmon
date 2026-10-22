# SPBM — DGX Spark and RTX Spark telemetry

## RTX Spark (N1X) support

Version `0.3.0.rtxspark.4` integrates the validated P16 register backend. The
ASUS ProArt P16 H7607BA with BIOS H7607BA.300 exposes **15 power readings, eight
temperatures, four power-limit controls and raw status/energy/diagnostic words**.
The original DGX `NVDA8800` backend remains separate.

### Discovery and firmware scope

Every N1X device must advertise the recognized `NVDA8810` MTEL flat-directory
schema (SPBM resource and unique aligned CFL/CPL/CBL/CCI/CPI entries). Existing
ACPI thermal-zone discovery remains available on matching N1X systems.
The expanded MMIO backend additionally requires exact ASUS/model/BIOS matching,
platform ID 2, and plausible firmware bounds and effective limits. Its mapping
is the independently validated 4 KiB region at `0x1c238000`; it is not derived
from the CPUEB directory or the incompatible `_CRS` resource positions.

Other N1X systems retain capability-detected ACPI temperatures. Power units and
MMIO access require a separately validated firmware quirk. This release does
not claim hardware validation for another laptop or BIOS.

### Available interfaces

Find the directory containing `name = spbm_n1x` under `/sys/class/hwmon/`.
Channel numbers are stable within this release, but scripts should locate
channels by their `*_label` files.

| Interface | Meaning |
|---|---|
| `power1/2` labels `sys_total`, `soc_pkg` | Existing ACPI power readings, retained with their original labels; firmware averages |
| `sys_instant`, `pkg_instant`, `cpu_gpu`, `cpu_p`, `cpu_e`, `vcore`, `gpu`, `prereg`, `dc_input` | Validated register power readings; microwatts |
| `pl1`, `pl2`, `syspl1`, `syspl2` | Firmware averaged power plus effective `powerN_cap`, current permitted `powerN_min/max`; microwatts |
| Eight `tempN_input` channels | Existing ACPI temperatures; millidegrees Celsius |
| `pl_level_raw`, `prochot_raw` | Unmodified 32-bit status words; PROCHOT polarity is unproven |
| `{pl1,pl2,syspl1,syspl2}_request_raw` | OS request register in mW; zero restores current EC defaults |
| `{pkg,cpu_e,cpu_p,gpc,gpu}_energy_{raw,overflow_raw,clear_raw}` | Fifteen separate read-only firmware words; no assumed scale, rollover extension or correction |
| `control_038_raw`, `diagnostic_{380,384,388,38c}_raw` | Read-only words with unresolved bit meanings/physical units |
| `pkg_temperature_c_raw` | Whole-degree package temperature word at `0x81c` |

GPU temperature and GPU power share a label, so consumers must also consider
the sensor class. Raw energy words are intentionally not exposed as standard
`energyN_input` values: absolute calibration and overflow semantics remain open.
No PROCHOT alarm or voltage/current sensor is invented from raw fields.

### Power limits

Only PL1, PL2, SysPL1 and SysPL2 are writable. Writes require whole milliwatts
expressed in microwatts, must meet the current firmware floor, and cannot exceed
either the firmware ceiling or the current EC default. Thus only validated
reductions are allowed. Write `0` to restore the **current**, potentially changing
EC default. `powerN_cap` reads the effective limit, not the OS request.

For example, after locating the `pl1` channel:

```sh
# Example only: check powerN_min/max before choosing a reduction.
echo 35000000 | sudo tee /sys/class/hwmon/hwmonX/powerN_cap
echo 0 | sudo tee /sys/class/hwmon/hwmonX/powerN_cap
```

The driver checks OS-request readback after writing and notifies firmware via
UPDATE_SPBM. Firmware applies control asynchronously; a successful write is
not proof of immediate physical limiting. SysPL1 took about 40 seconds to
become active in a sustained-load experiment. The four controllers' measured
physical effects are recorded in [the validation report](docs/validation/open-gaps-research.md).
On driver removal, only its own still-matching nonzero overrides are reset.
Avoid concurrent control writers and direct `/dev/mem` experiment scripts.
No fan control, boot change or automatic power-profile service is installed.

### Install and verify

Requires DKMS, a C compiler, and headers for the running kernel:

```sh
sudo ./scripts/install-dkms.sh
cat /sys/module/spbm/version
python3 tests/check-n1x.py --require-all --require-mmio  # validated P16 firmware
```

The installer builds before replacement, preserves other kernels, and restores
the previous DKMS version on failure. It verifies the loaded version and runs
the expanded runtime check on this P16 BIOS. DKMS rebuilds for future kernels
with installed headers. A busy module stops replacement before uninstalling it.
Use `python3 tests/check-n1x.py` without strict flags on other matching N1X systems.

```sh
python3 -m unittest discover -s tests -v
sudo python3 tests/check-n1x-controls.py  # P16 only: four temporary 1 W reductions
```

The latter requires all OS overrides to start at zero, verifies each effective
sysfs limit, and restores it immediately. It does not repeat the earlier
physical-load experiments. Offline tests exercise production C callbacks,
recorded hardware captures and, when vendor artifacts are supplied, original
Windows ARM64 helpers in Unicorn. See [reverse-engineering results](docs/validation/windows-decompiler-analysis.md)
and [remaining specification gaps](docs/n1x-register-contract.md).

## Original DGX Spark documentation

The remaining register maps, controls, examples and requirements describe the DGX backend, not the P16. Use the DKMS version above for this fork.

# DGX Spark Power Telemetry & Control hwmon Driver

Linux hwmon driver for the NVIDIA DGX Spark (GB10 SoC) that exposes
full system power telemetry and power limit controls via standard
`sensors` / sysfs interfaces.

The driver reads the System Power Budget Manager (SPBM) shared memory,
which is continuously updated by the MediaTek SSPM firmware with live
power readings in milliwatts, cumulative energy counters in millijoules,
and thermal zone temperatures in centidegrees Celsius. Writable
`power_cap` attributes allow setting OS-level power limits (PL1, PL2,
SysPL1, SysPL2).

> [!NOTE]
> NVIDIA has [officially stated](https://forums.developer.nvidia.com/t/help-needed-how-to-enable-grace-cpu-power-telemetry-on-dgx-spark-gb10/360631) there is "no method to monitor CPU power" on the DGX Spark.

> [!WARNING]
> This driver is vibe coded. Thanks Claude.

> [!WARNING]
> Update your BIOS with `fwupd` (`sudo fwupdmgr refresh && sudo fwupdmgr update`).
> Older firmware versions may report incorrect values for the CPU power channels.
> The SPBM interface is still in flux — if you notice incorrect or missing measurements,
> please [open an issue](https://github.com/antheas/spark_hwmon/issues).

## Sensors

### Power (14 channels)

| Channel | Idle | Description |
|---------|------|-------------|
| sys_total | ~25 W | Total system power |
| soc_pkg | ~17 W | SoC package |
| cpu_gpu | ~6 W | CPU + GPU combined |
| cpu_p | ~0.5 W | P-core cluster (10x Cortex-X925) |
| cpu_e | ~0.01 W | E-core cluster (10x Cortex-A725) |
| vcore | ~4 W | Core voltage domain |
| dc_input | ~26 W | DC input / charger rail |
| gpu | ~5 W | GPU power (matches nvidia-smi) |
| prereg | ~8 W | Pre-regulator input |
| dla | ~0.1 W | Deep Learning Accelerator |
| pl1 | ~18 W | EWMA power seen by PL1 controller (max=250W, cap=rw) |
| pl2 | ~18 W | EWMA power seen by PL2 controller (max=250W, cap=rw) |
| syspl1 | ~26 W | EWMA power seen by SysPL1 controller (max=300W, cap=rw) |
| syspl2 | ~27 W | EWMA power seen by SysPL2 controller (max=300W, cap=rw) |

### Energy (4 accumulators)

| Channel | Description |
|---------|-------------|
| pkg | Package energy (cumulative) |
| cpu_e | E-core energy (cumulative) |
| cpu_p | P-core energy (cumulative) |
| gpu | GPU energy (cumulative) |

Energy accumulators are more accurate than instantaneous power readings
for computing averages (the firmware uses a 100 ms PID control loop that
causes instantaneous values to oscillate).

### Temperature (8 zones)

| Channel | Idle | Description |
|---------|------|-------------|
| tj_max | ~31 C | Package Tj max |
| cpu_e_clu0 | ~31 C | E-core cluster 0 |
| cpu_p_clu0 | ~31 C | P-core cluster 0 |
| cpu_e_clu1 | ~31 C | E-core cluster 1 |
| cpu_p_clu1 | ~31 C | P-core cluster 1 |
| gpu | ~31 C | GPU |
| soc | ~31 C | SoC |
| dla | ~27 C | DLA |

### Status (custom sysfs)

| Attribute | Description |
|-----------|-------------|
| prochot | PROCHOT thermal throttle status (0 = normal) |
| pl_level | Current active power limit level |
| tj_max_c | Thermal rise above ambient (decidegrees, ~40 idle) |

### Power Limit Control (hwmon power_cap, read/write)

The `pl1`, `pl2`, `syspl1`, and `syspl2` power channels expose standard
hwmon `power_cap` (read/write), `power_max`, and `power_min` (read-only)
attributes, in microwatts. `power_max` and `power_min` read the firmware's
`LIMIT_HIGH` and `LIMIT_LOW` registers (absolute hardware ceiling/floor).
`power_cap` shows the effective limit (EC default when no OS override is set).
Writes outside the `power_min`..`power_max` range are rejected.
Write 0 to reset to the EC default.

Example: limit sustained power to 100W:

```bash
echo 100000000 | sudo tee /sys/class/hwmon/hwmonN/power11_cap
```

Reset to default:

```bash
echo 0 | sudo tee /sys/class/hwmon/hwmonN/power11_cap
```

Under full load (all 20 cores): ~92 W package, ~64 W CPU_P, ~10.5 W CPU_E.

Monitor all channels live:

```bash
watch -n 0.1 sensors 'spbm-*'
```

## Install via DKMS

```bash
sudo apt install dkms
sudo dkms add .
sudo dkms build spbm/0.3.0.rtxspark.3
sudo dkms install spbm/0.3.0.rtxspark.3
```

The module auto-loads at boot via ACPI modalias matching (`NVDA8800`).
DKMS automatically rebuilds the module on kernel updates.

To uninstall:

```bash
dkms status spbm | awk -F'[,/]' '{print $2}' | xargs -I{} sudo dkms remove spbm/{} --all
```

## Manual Build

```bash
make            # build and sign (requires MOK keys for Secure Boot)
sudo make load  # build, sign, load, show sensors
make unload     # unload module
make clean      # clean build artifacts
```

MOK signing keys are expected at `/var/lib/shim-signed/mok/MOK.{priv,der}`
(default Ubuntu location). Override with `MOK_KEY=` and `MOK_CERT=`.

## Requirements

- NVIDIA DGX Spark (GB10 SoC) with ACPI device `NVDA8800` (MTEL)
- Linux kernel 6.11+ (ARM64)
- Kernel headers (`linux-headers-$(uname -r)`)
- For Secure Boot: enrolled MOK key

## How It Works

The driver binds as an `acpi_driver` to the `NVDA8800` (MTEL) ACPI device.
At probe time, it queries the device's `_DSM` method
(UUID `12345678-1234-1234-1234-123456789abc`) to:

1. **Discover resources** (function 1): locate the SPBM memory region index
   among the device's `_CRS` resources
2. **Resolve registers** (function 2): map canonical register names to offsets
   within the SPBM region, rather than hard-coding addresses

This makes the driver resilient to firmware updates that change the memory
layout. Channels whose offsets cannot be resolved are automatically hidden.

The SPBM region was discovered by reverse-engineering the DSDT.
No upstream Linux driver exists as of kernel 7.0.

## License

GPL-2.0
