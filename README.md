# SPBM — DGX Spark and RTX Spark telemetry

## RTX Spark (N1X) support

This fork adds a **read-only, capability-detected** RTX Spark backend for the `NVDA8810` MTEL interface. It does not depend on a laptop vendor, model name or BIOS version. The original DGX Spark `NVDA8800` backend remains separate and unchanged.

### Firmware contract and discovery

Before registering sensors the driver requires:

- MTEL `_DSM` UUID `12345678-1234-1234-1234-123456789abc`, revision 0, advertising functions 1 and 2;
- a resource named `SPBM` in function 1;
- a flat name/offset directory in function 2 for that resource, containing unique `CFL`, `CPL`, `CBL`, `CCI` and `CPI` entries, with aligned 32-bit offsets;
- at least one supported ACPI thermal-zone object with a `_TMP` accessor.

Malformed or unknown firmware schemas are rejected. The driver does **not** interpret those offsets or map MMIO; the directory identifies the recognized RTX Spark firmware ABI. Other ACPI IDs and incompatible schemas need a separately validated backend or a small documented quirk, not a forced match.

Individual sensors are discovered independently. Missing optional sensors are hidden, so a machine can expose only temperatures, only power, or a subset. Invalid firmware samples return `ENODATA` instead of bogus readings. The driver evaluates existing `\_TZ.*._TMP` methods:

| hwmon channel | ACPI zone | Firmware units | hwmon units |
|---|---|---|---|
| `sys_total` | `PSYS` | mW | µW |
| `soc_pkg` | `PSOC` | mW | µW |
| `soc`, CPU E/P clusters 0/1, `gpu`, `dla`, `uncore` | `TSOC`, `TS0E`, `TS0P`, `TS1E`, `TS1P`, `TGPU`, `TDLA`, `TUNC` | decikelvin | millidegrees Celsius |

Power additionally requires `_CRT` to return `0x7fffffff`, the firmware's nonthermal telemetry marker. A normal thermal zone with a genuine critical temperature is not reclassified as power. The mW interpretation is the firmware contract observed on this P16 and documented by [Omarchy's Dell N1X thermal fix](https://github.com/omacom/omarchy-pkgs/blob/master/pkgbuilds/linux-omarchy-aarch64/1012-n1x-acpi-thermal-skip-power-telemetry.patch); it is not a standard ACPI `_TMP` unit. Matching interface names alone is not independent proof of accurate readings on untested firmware.

This driver only reports telemetry. It does not repair thermal trip points, unregister firmware power zones from the thermal subsystem, control fans, expose power-limit writes, or supply missing GPU/CPU power subdivisions.

### Validation

| Machine | BIOS | Kernel | Result |
|---|---|---|---|
| ASUS ProArt P16 H7607BA | H7607BA.300 | 7.2.8-23-omarchy-p16-asus | Ten channels, temperature agreement and read-only access verified |
| Other RTX Spark N1X systems | Not yet tested | — | Accepted only if the firmware contract above matches; measurements still need validation |

On another machine, run `python3 tests/check-n1x.py` after loading. It accepts missing optional channels and checks ranges, labels, absence of power controls, and agreement with thermal-zone temperatures where available. For the validated P16, use `--require-all` to require all ten channels. Compare power against battery discharge or external measurements under idle/load; on AC, charging and display power must be accounted for. Test unload/reload and suspend/resume, and record model, BIOS, kernel, channel list and errors. No other machine is claimed as hardware-tested.

Portable checks for the validation tool:

```sh
python3 -m unittest discover -s tests -v
```

These exercise optional-channel handling and failure cases; they do not emulate or validate another machine's ACPI firmware.

### Install this fork with DKMS

```sh
sudo install -d /usr/src/spbm-0.3.0.rtxspark.2
sudo install -m644 spbm.c Makefile dkms.conf /usr/src/spbm-0.3.0.rtxspark.2/
sudo dkms add -m spbm -v 0.3.0.rtxspark.2
sudo dkms build -m spbm -v 0.3.0.rtxspark.2 -k "$(uname -r)"
sudo dkms install -m spbm -v 0.3.0.rtxspark.2 -k "$(uname -r)"
sudo modprobe spbm
sensors spbm_n1x-*
```

The `NVDA8810` modalias loads the module automatically where the module is installed; DKMS rebuilds for kernel updates with installed headers. Install for older fallback kernels separately if needed. Do not install over an existing upstream `spbm` version without removing that version first.

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
sudo dkms build spbm/0.3.0.rtxspark.2
sudo dkms install spbm/0.3.0.rtxspark.2
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
