# QEMU Prebuilt v3 — ESP32 simulation runtime assets

Known-good QEMU libraries and ESP32 ROM images for Velxio OSS (IoT-Studio
developer bootstrap). This release replaces the incompatible binaries that
were previously tracked in the repository.

## Why v3

The previously distributed `libqemu-xtensa.so` / `libqemu-riscv32.so` were
linked against glibc 2.43. The Velxio OSS Docker runtime is Debian 13
(glibc 2.41), so every ESP32 simulation crashed with:

    OSError: /lib/x86_64-linux-gnu/libm.so.6: version `GLIBC_2.43' not found
    [esp32_worker] worker exited unexpectedly (code 1)

The v3 binaries are linked against glibc 2.34, which every supported
runtime provides.

## Requirements

| Dependency          | Version | Notes                                    |
|---------------------|---------|------------------------------------------|
| Architecture        | x86-64  | linux/amd64 only                         |
| glibc               | >= 2.34 | hard floor; Debian 11/12/13, Ubuntu 20.04–24.04 |
| GCC (build toolchain) | 11.4.0 | Ubuntu 22.04 toolchain                   |
| libfdt.so.1         | any     | `apt install libfdt1` (part of base Debian images; needed on minimal Ubuntu) |
| libgcrypt.so.20     | any     | `apt install libgcrypt20`                |
| libz.so.1           | any     | `apt install zlib1g`                    |

## Contents

    libqemu-xtensa.so        44.8 MB   ESP32 / ESP32-S3 / ESP32-S2 emulation
    libqemu-riscv32.so       41.8 MB   ESP32-C3 emulation
    esp32-v3-rom.bin         446 KB    ESP32 ROM (v3)
    esp32-v3-rom-app.bin     446 KB    ESP32 ROM app image
    esp32c3-rom.bin          384 KB    ESP32-C3 ROM
    esp32s3_rev0_rom.bin     384 KB    ESP32-S3 ROM (rev0)

## Install

Drop the files into the IoT-Studio checkout's `prebuilt/` directory, or let
`build.py` fetch this bundle automatically when local assets are missing or
fail validation:

    git clone https://github.com/ZhadowValker/IoT-Studio.git
    cd IoT-Studio
    python3 build.py          # auto-downloads this release if needed

## Verification

- `ctypes.CDLL()` loads cleanly inside the Debian 13 runtime image
- ESP32 worker reaches `system: booted` with a compiled blink sketch
  (verified end-to-end: compile → worker → boot in 0.1s)
- Symbols exported: `qemu_picsimlab_get_internals`, `bql_lock_impl`,
  `bql_unlock` (modern QEMU BQL lock names required by the ESP32 worker)

## Building your own

Build QEMU (lcgamboa `picsimlab-esp32` fork) inside a `debian:12` container
(or any environment with glibc <= the version of your oldest target runtime)
to guarantee forward compatibility. Never build on a bleeding-edge distro —
binaries linked against a newer glibc than the runtime cannot load, ever.