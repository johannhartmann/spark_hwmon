# Native N1X backend integration

Version `0.3.0.rtxspark.5` implements the contracts established by the recorded
load experiments and original Windows-reader execution. Scope is ASUS ProArt
P16 H7607BA, BIOS H7607BA.300; the general N1X ACPI fallback remains available.

## Implemented

- Existing two ACPI power channels and eight ACPI temperature channels retained.
- Nine additional register power channels and four firmware average/control
  channels: 15 power readings in total, with standard microwatt conversion.
- Four reduction-only power controls, current EC/firmware ceiling enforcement,
  whole-mW validation before narrowing, serialized writes and OS readback.
- Zero reset to current EC defaults and unload cleanup restricted to this
  driver's still-matching overrides; no automatic profile is applied at probe.
- Twenty-seven read-only raw attributes: two statuses, five unresolved control/
  diagnostic words, 15 energy words, four OS requests and whole-degree package
  temperature. No guessed alarm polarity or calibrated energy interface.
- DKMS source staging includes the new header. Installer checks the expanded
  runtime interface and rolls back on failure for this validated P16 firmware.

The MMIO path requires the exact firmware quirk, recognized MTEL schema,
platform ID 2 and plausible live limits/temperature. It maps the vendor-defined
4 KiB region, independently of the CPUEB aliases. Other N1X systems do not
inherit this address contract solely from the shared chip or ACPI ID.

## Verification

`make modules W=1` builds against `7.2.8-23-omarchy-p16-asus` without warnings.
All 59 tests pass with the pinned Windows artifacts; without them 23 opt-in
vendor tests skip explicitly. New tests exercise the actual production C cap
callbacks against RAM: negative/fractional/overflow inputs, firmware floor/EC
ceiling, effective readback, zero reset, no-MMIO visibility and cleanup that
preserves an external writer's replacement request. Runtime-check fixtures
cover simultaneous GPU temperature/power labels and rejection of invented
standard energy values.

Live installation and control verification are recorded below after the DKMS
replacement completes. The earlier physical load experiments are not repeated:
`tests/check-n1x-controls.py` makes four temporary 1 W reductions and restores
each immediately, requiring initially zero OS requests.

## Remaining specification gaps

The absolute energy scale/accounting, overflow/reset arithmetic, physical
PROCHOT polarity and packed diagnostic units are still open. Raw access makes
these observable without embedding unsupported interpretations. Firmware
filtering and asynchronous controller response remain firmware behavior; a
successful OS-request write is not an instantaneous physical-power guarantee.
