# Velxio Local Full Profile Build

This repository contains the downstream automation script for building and running a local Velxio development environment without Docker.

## Purpose

The current `build.py` is designed to bootstrap the **full profile** for Velxio local development.

The full profile includes:

```text
browser profile
+ ESP32
+ ESP32-C3
+ ESP-IDF
+ native QEMU .so libraries
```

In practical terms, this means the script sets up:

- Velxio upstream source clone
- Backend Python virtual environment
- Frontend Node/Vite development environment
- Arduino CLI
- AVR board support
- RP2040 board support
- ESP32 Arduino core 2.0.17
- ESP-IDF v4.4.7
- Native QEMU libraries
  - `libqemu-xtensa.so`
  - `libqemu-riscv32.so`
- ESP32 ROM blobs
  - `esp32-v3-rom.bin`
  - `esp32-v3-rom-app.bin`
  - `esp32c3-rom.bin`
- Writable ESP-IDF build cache under `/var/lib/velxio-build`
- Writable ccache directory under `/var/cache/ccache`
- Frontend startup fix for `npx tsx` prompt
- ESP-IDF exported runtime environment for backend compilation

## Folder Structure

The script creates and uses the following structure:

```text
project-root/
  build.py
  our-velxio/
    upstream/
      velxio/
        backend/
        frontend/
        scripts/
        test/
    downstream/
      config/
        espidf.env
        qemu.env
        bootimages.env
      cache/
        esp-idf/
        arduino-esp32/
        qemu-lcgamboa/
        boot-images/
      lib/
        libqemu-xtensa.so
        libqemu-riscv32.so
        esp32-v3-rom.bin
        esp32-v3-rom-app.bin
        esp32c3-rom.bin
        boot-images/
      logs/
        backend.out.log
        frontend.out.log
        build.log
      validation/
        full_profile_report.md
      velxio.lock.json
```

## Profiles

### Browser Profile

The browser profile is the lightweight profile.

```text
browser = backend + frontend + AVR + RP2040
```

Use this when working only on:

- Arduino Uno
- Arduino Mega
- Arduino Nano
- ATtiny
- Raspberry Pi Pico
- Browser-side simulation
- Frontend or UI work

Command:

```bash
python3 build.py bootstrap --profile browser
```

### Full Profile

The full profile is the current validated profile.

```text
full = browser + ESP32 + ESP32-C3 + ESP-IDF + native QEMU .so
```

Use this when working on:

- ESP32
- ESP32-S3
- ESP32-C3
- QEMU-backed emulation
- ESP-IDF compilation
- Native `.so` integration
- Full local parity with Docker for ESP32-family boards

Command:

```bash
python3 build.py bootstrap --profile full --qemu-provider source
```

## Main Commands

### Run Full Bootstrap

```bash
python3 build.py bootstrap --profile full --qemu-provider source
```

This performs the full setup:

1. Creates `our-velxio` structure.
2. Clones upstream Velxio.
3. Installs/checks OS packages.
4. Sets up backend Python venv.
5. Installs frontend dependencies.
6. Installs Arduino CLI and board cores.
7. Installs ESP32 Arduino core 2.0.17.
8. Installs ESP-IDF v4.4.7.
9. Builds QEMU native `.so` files from source.
10. Copies ROM files.
11. Writes environment files.
12. Validates the environment.
13. Writes lock and validation reports.

### Start Services

```bash
python3 build.py start
```

Expected output:

```text
Backend:  http://127.0.0.1:8001
Frontend: http://127.0.0.1:5173
```

### Stop Services

```bash
python3 build.py stop
```

### Check Status

```bash
python3 build.py status
```

### Run Doctor

```bash
python3 build.py doctor --profile full
```

### Run Smoke Test

```bash
python3 build.py smoke --profile full
```

## Opening from Windows Browser when Running in WSL

From WSL, run:

```bash
cmd.exe /C start http://127.0.0.1:5173
```

Or manually open this in Windows browser:

```text
http://127.0.0.1:5173
```

## Logging

### Capture bootstrap log

```bash
set -o pipefail
python3 build.py bootstrap --profile full --qemu-provider source 2>&1 | tee log.txt
echo "Exit code: ${PIPESTATUS[0]}" | tee -a log.txt
```

### Backend log

```bash
tail -100 our-velxio/downstream/logs/backend.out.log
```

### Frontend log

```bash
tail -100 our-velxio/downstream/logs/frontend.out.log
```

## Important Fixes Included

### 1. ESP-IDF Python Environment Export

The backend must run with the ESP-IDF exported environment.

The script loads the environment equivalent to:

```bash
source our-velxio/downstream/cache/esp-idf/export.sh
```

This ensures the backend uses:

- `IDF_PATH`
- `IDF_TOOLS_PATH`
- `IDF_PYTHON_ENV_PATH`
- ESP-IDF Python virtual environment
- ESP-IDF toolchain paths

Without this, ESP-IDF compile may fail with messages like:

```text
IDF_PYTHON_ENV_PATH: (not set)
Python interpreter used: /usr/bin/python
Some Python dependencies must be installed
```

### 2. Ubuntu 24.04 Python / PEP 668 Fix

Ubuntu 24.04 blocks some `pip --user` operations because of externally managed Python environments.

The script installs/checks these packages when needed:

```bash
python3-full
python3-virtualenv
python-is-python3
```

This prevents ESP-IDF v4.4.7 from failing while trying to install `virtualenv`.

### 3. QEMU Source Build Fix

The script builds QEMU native libraries using the lcgamboa build script instead of calling QEMU `configure` with unsupported flags.

Expected outputs:

```text
libqemu-xtensa.so
libqemu-riscv32.so
```

These are copied into:

```text
our-velxio/downstream/lib/
```

### 4. Frontend `npx tsx` Prompt Fix

The frontend generator uses:

```bash
npx tsx scripts/generate-component-metadata.ts
```

When started in the background, `npx` cannot ask:

```text
Ok to proceed? (y)
```

The script fixes this by:

- Installing `tsx` at the upstream repo root.
- Starting frontend with `npm_config_yes=true`.
- Starting frontend with `CI=true`.

### 5. Writable ESP-IDF Build Directory

ESP-IDF compile uses:

```text
/var/lib/velxio-build
```

In WSL/manual mode, this directory must be writable by the current user.

The script ensures:

```bash
sudo mkdir -p /var/lib/velxio-build /var/cache/ccache
sudo chown -R $(id -u):$(id -g) /var/lib/velxio-build /var/cache/ccache
chmod -R u+rwX /var/lib/velxio-build /var/cache/ccache
```

## Validation Status

The current full profile has been validated for:

- Backend startup
- Frontend startup
- ESP-IDF environment export
- ESP32-C3 compile
- ESP32-C3 compiled program returned
- ESP32-C3 QEMU run started
- Native QEMU `.so` load through Python `ctypes`

## Known Non-Blocking Console Messages

The following messages are expected in development mode and are not blockers:

```text
Download the React DevTools for a better development experience
Lit is in dev mode
/api/projects/featured?limit=12 404
/api/metrics/run 404
pinPositionCalculator Component ... not found in DOM
```

These do not prevent ESP32/ESP32-C3 compile and QEMU run.

## Raspberry Pi Images

Raspberry Pi image support is intentionally treated as a separate phase.

Raspberry Pi emulation needs large boot assets such as:

- Kernel image
- Device tree
- Raspberry Pi OS image
- Boot image cache

The recommended future profile model is:

```text
browser profile
  AVR + RP2040

full profile
  browser + ESP32 + ESP32-C3 + ESP-IDF + native QEMU .so

pi profile
  full + Raspberry Pi boot image provider + Pi image cache
```

Suggested downstream paths:

```text
our-velxio/downstream/lib/boot-images/
our-velxio/downstream/cache/boot-images/
our-velxio/downstream/config/bootimages.env
```

Suggested environment:

```bash
export VELXIO_BOOT_IMAGES_LOCAL_DIR="/absolute/path/to/our-velxio/downstream/lib/boot-images"
export VELXIO_BOOT_IMAGE_CACHE_DIR="/absolute/path/to/our-velxio/downstream/cache/boot-images"
```

## Recommended Git Workflow

Check files:

```bash
git status
```

Add files:

```bash
git add build.py README.md
```

Commit:

```bash
git commit -m "feat(build): add full local Velxio profile with ESP-IDF and native QEMU"
```

## Troubleshooting

### Frontend does not open

Check:

```bash
tail -100 our-velxio/downstream/logs/frontend.out.log
```

If you see an `npx tsx` prompt, rerun bootstrap:

```bash
python3 build.py bootstrap --profile full --qemu-provider source
python3 build.py start
```

### Backend starts but ESP32 compile fails

Check:

```bash
tail -150 our-velxio/downstream/logs/backend.out.log
```

Look for:

```text
IDF_PYTHON_ENV_PATH
Python interpreter used
Permission denied: /var/lib/velxio-build
```

Then rerun:

```bash
python3 build.py stop
python3 build.py bootstrap --profile full --qemu-provider source
python3 build.py start
```

### Windows browser cannot open WSL app

Run from WSL:

```bash
cmd.exe /C start http://127.0.0.1:5173
```

## Current Success Criteria

The full profile is considered successful when all of these are true:

```text
Backend starts on port 8001
Frontend starts on port 5173
ESP32-C3 compiles successfully
ESP32-C3 returns compiledProgram
ESP32-C3 QEMU run starts
Native QEMU .so loads through ctypes
```
