# IoT-Studio — Velxio OSS Developer Bootstrap

One-command local setup for [Velxio OSS](https://github.com/ZhadowValker/velxio) —
a fully local, browser-based Arduino and ESP32 simulator with **real QEMU emulation**.

```bash
git clone https://github.com/ZhadowValker/IoT-Studio.git
cd IoT-Studio
python3 build.py
```

That single command:

1. validates your host (git, docker, python3, curl, Docker daemon, Compose v2)
2. validates the QEMU emulation assets in `prebuilt/` (see [below](#the-prebuilt-binaries))
3. shallow-clones the Velxio OSS source (`ZhadowValker/velxio`, branch `oss`) into `our-velxio/upstream/`
4. copies the QEMU assets into the source tree
5. builds the strict OSS Docker image (Debian 13 · nginx + FastAPI · ESP-IDF v5)
6. starts the container and waits for the health endpoint
7. prints a build summary (image, container, volumes) and the app URL

When it finishes, the app is at **http://localhost:3080** — open it, pick a board,
write a sketch, click Run. ESP32 sketches compile with the real ESP-IDF toolchain
and boot on a real QEMU emulator inside the container.

No GitHub CLI, no GitHub token, no Git identity, no Pro license, no manual
downloads are required.

---

## Contents

- [Requirements](#requirements)
- [Commands](#commands)
- [What the setup does](#what-the-setup-does)
- [The prebuilt binaries](#the-prebuilt-binaries)
- [QEMU binary compatibility (glibc)](#qemu-binary-compatibility-glibc)
- [Folder structure](#folder-structure)
- [Version history](#version-history)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)

---

## Requirements

| Requirement | Notes |
|---|---|
| Linux x86-64 (or WSL2) | the QEMU binaries are `linux/amd64` only |
| `git`, `python3`, `curl` | any recent version |
| Docker Engine | daemon running (`docker info` must succeed) |
| Docker Compose v2 | `docker compose version` (the plugin, not the old `docker-compose` binary) |

Disk: the built image is ~5 GB. RAM: 4 GB+ recommended.
First build on a virgin machine takes **~8–9 minutes** (dominated by the ESP-IDF
v5 clone and toolchain downloads). Subsequent rebuilds are ~1–2 min thanks to
Docker layer cache.

---

## Commands

All commands run from the repo root. `python3 build.py` with no arguments is
the same as `setup`.

| Command | What it does |
|---|---|
| `python3 build.py setup` | Full flow: validate → clone → build → start → health check → summary |
| `python3 build.py build` | Build (or rebuild) the Docker image only |
| `python3 build.py build --no-cache` | Build with no Docker cache (fully clean) |
| `python3 build.py rebuild [--no-cache]` | Build + restart + health check + summary |
| `python3 build.py start` | Start the stack (clones/validates if needed, no image rebuild) |
| `python3 build.py stop` | Stop the container |
| `python3 build.py restart` | Restart the container + health check |
| `python3 build.py status` | Docker Compose `ps` table |
| `python3 build.py summary` | Print the image, container and volumes summary on demand |
| `python3 build.py logs` | Last 200 container log lines |
| `python3 build.py qemu` | Re-validate + re-sync QEMU assets only |
| `python3 build.py doctor` | Diagnose the environment (7 checks) |
| `python3 build.py clean [--volumes]` | Remove this project's Docker resources (containers, networks). `--volumes` also removes the named build/ccache volumes |

Everything is idempotent — re-running `setup` or `start` on an existing
installation is safe and fast.

---

## What the setup does

```text
IoT-Studio (this repo)                our-velxio/upstream  (generated)
├── build.py                         ├── backend/            (FastAPI)
├── prebuilt/          ── copy ──►  ├── frontend/           (React + Vite)
│   └── QEMU assets                  ├── Dockerfile.oss
└── README.md                        ├── docker-compose.oss.yml
                                     └── prebuilt/qemu/      (copied assets)
                                          │
                              docker compose build (context: this tree)
                                          │
                                          ▼
                            image: velxio-oss-velxio-oss (~5 GB)
                                   container: velxio-oss
                                   http://localhost:3080
```

- The Velxio **source** is never committed here — it is shallow-cloned from
  `ZhadowValker/velxio` branch `oss` on first run and verified against a file
  contract (`Dockerfile.oss`, `docker-compose.oss.yml`, `vite.oss.config.ts`,
  `build-oss.mjs`).
- The `oss` branch ships **without binaries**. This repository is the binary
  provider: the QEMU libraries and ROMs in `prebuilt/` get copied into the
  cloned tree and baked into the Docker image at `/app/lib/`.
- The image build is "strict OSS": no Pro overlay, no license key, no telemetry.
- Two named volumes (`velxio-oss-build`, `velxio-oss-ccache`) persist ESP-IDF
  build state and compiler cache across restarts. The **first** ESP32 compile
  takes ~60 s (cold volume); after that, compiles are ~2 s.

---

## The prebuilt binaries

`prebuilt/` contains the six files that make ESP32-family emulation real.
Two kinds:

### QEMU emulator libraries (the `.so` files)

Compiled from the [lcgamboa QEMU fork](https://github.com/lcgamboa/qemu)
(`picsimlab-esp32` branch) as **shared libraries** instead of executables. The
backend loads them from Python with `ctypes` — one library instance per
simulation, so multiple boards can run in parallel without shared-state
conflicts.

| File | Emulates | Boards |
|---|---|---|
| `libqemu-xtensa.so` (~45 MB) | Xtensa LX6/LX7 cores | ESP32, ESP32-S3, ESP32-S2 |
| `libqemu-riscv32.so` (~42 MB) | RISC-V cores | ESP32-C3, ESP32-C6 |

These provide real instruction-level emulation — GPIO, UART, timers, ADC,
PWM/LEDC, I2C/SPI, WiFi radio modeling — not a JavaScript approximation.

### ESP32 ROM images (the `.bin` files)

Real hardware boots from factory-masked ROM code before it ever touches your
sketch; QEMU needs the same ROMs to boot the same way:

| File | Purpose |
|---|---|
| `esp32-v3-rom.bin` | ESP32 (v3 silicon) ROM — bootloader handoff, flash read |
| `esp32-v3-rom-app.bin` | ESP32 ROM app image — direct-app boot path |
| `esp32c3-rom.bin` | ESP32-C3 ROM |
| `esp32s3_rev0_rom.bin` | ESP32-S3 (rev0) ROM |

### Where they come from / alternatives

The known-good binaries are also published as a GitHub Release —
[`qemu-prebuilt-v3`](https://github.com/ZhadowValker/IoT-Studio/releases/tag/qemu-prebuilt-v3) —
with full dependency documentation. If `prebuilt/` is missing or contains
invalid/incompatible binaries, `build.py` **automatically downloads the
release bundle** and re-validates. To build your own set instead, compile the
fork in a `debian:12` container (see the release notes for the rule).

---

## QEMU binary compatibility (glibc)

This bit us once, so it is enforced now — read this if you replace the binaries.

The Docker runtime stage is **Debian 13 (glibc 2.41)**. A glibc-linked binary
only runs on glibc **equal to or newer than** what it was linked against —
never older. The distributed set is linked against **glibc 2.34**, so it runs
on Debian 11/12/13 and Ubuntu 20.04–24.04.

`build.py` scans every `.so` for `GLIBC_x.y` requirements and **rejects
anything needing newer than 2.41** with an actionable error — before any
Docker build — instead of letting the ESP32 worker crash at first Run with
the cryptic `worker exited unexpectedly (code 1)`.

Runtime dependencies of the libraries (satisfied by the base image; needed if
you use them outside Docker): `libfdt1`, `libgcrypt20`, `zlib1g`.
Build toolchain of the distributed set: **GCC 11.4.0** (Ubuntu 22.04).

---

## Folder structure

After a successful setup:

```text
IoT-Studio/
├── build.py               # the bootstrap script (this repo)
├── README.md
├── docs-QEMU-PREBUILT-v3.md
├── prebuilt/              # QEMU assets (tracked, known-good)
└── our-velxio/            # generated at runtime — never committed
    └── upstream/          # shallow clone of velxio@oss
        ├── backend/  frontend/  Dockerfile.oss  docker-compose.oss.yml
        └── prebuilt/qemu/  # assets copied here before the image build
```

`our-velxio/` is in `.gitignore`. If it ever gets in the way, delete it —
the next run re-clones.

---

## Version history

The `2.x-oss-developer` line is the current script lineage and supersedes the
older native (pre-Docker) scripts and the `3.0.0-oss-dual-mode` interim
release. Versions below are listed oldest → newest.

### v1.x — native full-profile bootstrap (superseded)

The original no-Docker flow: `build.py bootstrap --profile browser|full`,
local Python venv + Node/Vite dev servers on ports 8001/5173, Arduino CLI with
AVR/RP2040/ESP32 cores, ESP-IDF v4.4.7, and QEMU compiled **from source** on
the host. Worked, but was slow to set up, host-dependent, and hard to keep
reproducible. Retained only for historical reference.

### v3.0.0-oss-dual-mode (superseded)

Transitional Docker/native dual-mode script. Introduced the Docker OSS path,
but tracked generated runtime state in Git (`our-velxio/` logs, caches,
nested clones) which broke fresh clones, and shipped QEMU binaries linked
against **glibc 2.43** — a version no stable distro provides — so every ESP32
simulation crashed inside the Debian 13 runtime image.

### v2.0.0-oss-developer — the rewrite

Ground-up rewrite to a strict Docker-only, single-command bootstrap:

- One command = full setup (validate → clone velxio@oss → sync assets →
  `docker compose build` → `up -d` → health poll on `:3080/health`)
- Zero-auth design: no gh CLI, no token, no Git identity, no license key
- QEMU asset validation (presence, size, ELF magic)
- Velxio checkout contract verification (required files + branch pin)
- Full subcommand surface: `setup build rebuild start stop restart status
  logs qemu doctor clean`
- `doctor`: 7-check environment diagnosis
- `clean`: project-scoped Docker teardown only

### v2.1.0 — the glibc fix + self-healing assets

Fixes the crash that shipped with v3.0.0 and makes bad assets impossible to
miss:

- **Replaced the broken binaries** (glibc 2.43) with the known-good set
  linked against glibc 2.34 (GCC 11.4.0 / Ubuntu 22.04 toolchain) in all
  tracked locations
- **glibc ceiling validation**: every `.so` is scanned for `GLIBC_x.y`
  requirements; anything newer than 2.41 is rejected at bootstrap with a
  clear explanation instead of crashing the ESP32 worker at first Run
- **Auto-download fallback**: if `prebuilt/` is missing or invalid, the
  script fetches the `qemu-prebuilt-v3` release bundle automatically and
  re-validates
- **Fixed `doctor` crash**: `compose()` did not accept the `check` kwarg that
  `doctor` passes — every `doctor` run died with a `TypeError`
- **Repo layout cleanup**: removed 18 tracked runtime-state files that made
  fresh clones fail with "not a valid Velxio Git checkout"; `our-velxio/`
  is now gitignored and fully generated
- Published [`qemu-prebuilt-v3`](https://github.com/ZhadowValker/IoT-Studio/releases/tag/qemu-prebuilt-v3)
  with the dependency documentation

### v2.2.0 — build summary (current)

- `setup` and `rebuild` now print a **build summary** after success: image
  name + sha256 + size + build time, container status and port mapping,
  compose volumes, app URL, source checkout location, and the stack
  description
- New `summary` subcommand to print the same block on demand
- Cosmetic: container line renders as `Up ... (ports)` instead of a raw
  pipe-separated format

---

## Troubleshooting

**`worker exited unexpectedly (code 1)` when clicking Run on an ESP32 board**

The QEMU library failed to load. On v2.1.0+ this is caught at bootstrap by
the glibc check. If you replaced `prebuilt/*.so` yourself, restore the
known-good set (`python3 build.py qemu` re-validates; or delete `prebuilt/`
and re-run setup to auto-download the release).

**`Existing Velxio checkout is on '…', expected 'oss'`**

`our-velxio/upstream` was checked out on a different branch (or detached
HEAD). Either `git checkout oss` inside it, or delete `our-velxio/` and
re-run — it re-clones.

**`…exists but is not a valid Velxio Git checkout`**

Something non-Git is occupying `our-velxio/upstream`. Move it aside (or
delete it) and re-run.

**Port 3080 already in use**

Another stack (possibly an older Velxio deployment) owns the port:
`docker ps --filter name=velxio` to find it, then `docker rm -f velxio-oss`,
or stop whatever else holds 3080.

**`Velxio OSS did not become healthy within 180 seconds`**

Check `python3 build.py logs`. Common causes: first boot on a slow machine
(ESP-IDF setup on first compile), or the container crash-looping — the logs
will say which.

**`doctor` reports the health endpoint as FAIL while the stack is stopped**

Expected: doctor checks the live endpoint, and a stopped stack is "not
running", not "broken". Run `python3 build.py start`, then doctor again.

**Docker daemon not available**

Start Docker Desktop / `systemctl start docker` and re-run. `clean` also
requires a live daemon (a `down` against a dead daemon has nothing to talk
to).

---

## Uninstall

Everything lives inside Docker, scoped to project `velxio-oss`:

```bash
python3 build.py clean --volumes   # containers, networks, named volumes
docker rmi velxio-oss-velxio-oss   # the image
rm -rf our-velxio/                 # the generated source tree
```

Nothing else on your machine is touched. Reinstall any time with
`python3 build.py`.