#!/usr/bin/env python3
"""
IoT-Studio -> Velxio OSS developer bootstrap.

Developer flow:
    git clone https://github.com/ZhadowValker/IoT-Studio.git
    cd IoT-Studio
    python3 build.py

IoT-Studio is the developer entry point.
The script obtains the public Velxio OSS source, supplies the QEMU
prebuilt assets from this repository, builds the strict OSS Docker image,
starts it, and verifies the health endpoint.

No GitHub CLI, GitHub token, Git identity, Pro license, or Pro download
is required.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


VERSION = "2.0.0-oss-developer"

VELXIO_REPO = "https://github.com/ZhadowValker/velxio.git"
VELXIO_BRANCH = "oss"

VELXIO_DIR = Path("our-velxio") / "upstream"
QEMU_SOURCE_DIR = Path("prebuilt")
QEMU_TARGET_DIR = VELXIO_DIR / "prebuilt" / "qemu"

COMPOSE_FILE = "docker-compose.oss.yml"
COMPOSE_PROJECT = "velxio-oss"
HEALTH_URL = "http://localhost:3080/health"

QEMU_FILES = (
    "libqemu-xtensa.so",
    "libqemu-riscv32.so",
    "esp32-v3-rom.bin",
    "esp32-v3-rom-app.bin",
    "esp32c3-rom.bin",
    "esp32s3_rev0_rom.bin",
)

REQUIRED_VELXIO_FILES = (
    "Dockerfile.oss",
    "docker-compose.oss.yml",
    "frontend/vite.oss.config.ts",
    "frontend/scripts/build-oss.mjs",
)


class BuildError(RuntimeError):
    pass


def root() -> Path:
    return Path(__file__).resolve().parent


def log(message: str) -> None:
    print(f"INFO: {message}")


def success(message: str) -> None:
    print(f" OK : {message}")


def warning(message: str) -> None:
    print(f"WARN: {message}")


def error(message: str) -> None:
    print(f"FAIL: {message}")


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(command))
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=check,
    )


def exists(command: str) -> bool:
    return shutil.which(command) is not None


def check_host() -> None:
    missing = [
        command for command in ("git", "docker", "python3", "curl")
        if not exists(command)
    ]
    if missing:
        raise BuildError("Missing required commands: " + ", ".join(missing))

    result = run(["docker", "info"], capture=True, check=False)
    if result.returncode != 0:
        raise BuildError(
            "Docker is installed but the Docker daemon is not available. "
            "Start Docker Desktop/Docker Engine and try again."
        )

    result = run(["docker", "compose", "version"], capture=True, check=False)
    if result.returncode != 0:
        raise BuildError("Docker Compose v2 is required.")

    success("Host prerequisites verified")


def validate_provider_assets() -> None:
    missing = []
    invalid = []

    for name in QEMU_FILES:
        path = root() / QEMU_SOURCE_DIR / name

        if not path.is_file():
            missing.append(name)
            continue

        if path.stat().st_size < 1024:
            invalid.append(name)
            continue

        if path.suffix == ".so":
            with path.open("rb") as handle:
                if handle.read(4) != b"\x7fELF":
                    invalid.append(name)

    if missing:
        raise BuildError(
            "IoT-Studio prebuilt directory is missing:\n"
            + "\n".join(f"  - {name}" for name in missing)
        )

    if invalid:
        raise BuildError(
            "Invalid QEMU prebuilt asset(s):\n"
            + "\n".join(f"  - {name}" for name in invalid)
        )

    success("IoT-Studio QEMU assets verified")


def sync_qemu() -> None:
    source = root() / QEMU_SOURCE_DIR
    target = root() / QEMU_TARGET_DIR
    target.mkdir(parents=True, exist_ok=True)

    for name in QEMU_FILES:
        shutil.copy2(source / name, target / name)

    success(f"QEMU assets copied to {target}")


def clone_velxio() -> None:
    destination = root() / VELXIO_DIR

    if (destination / ".git").is_dir():
        branch = run(
            ["git", "branch", "--show-current"],
            cwd=destination,
            capture=True,
        ).stdout.strip()

        if branch != VELXIO_BRANCH:
            raise BuildError(
                f"Existing Velxio checkout is on '{branch or 'detached HEAD'}', "
                f"expected '{VELXIO_BRANCH}'."
            )

        success("Existing Velxio OSS checkout found")
        return

    if destination.exists() and any(destination.iterdir()):
        raise BuildError(
            f"{destination} exists but is not a valid Velxio Git checkout. "
            "Move it aside and run setup again."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)

    log(f"Cloning Velxio OSS branch into {destination}")
    run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            VELXIO_BRANCH,
            VELXIO_REPO,
            str(destination),
        ]
    )

    success("Velxio OSS source cloned")


def verify_velxio() -> None:
    destination = root() / VELXIO_DIR

    missing = [
        path for path in REQUIRED_VELXIO_FILES
        if not (destination / path).is_file()
    ]

    if missing:
        raise BuildError(
            "Velxio OSS checkout is incomplete. Missing:\n"
            + "\n".join(f"  - {name}" for name in missing)
        )

    branch = run(
        ["git", "branch", "--show-current"],
        cwd=destination,
        capture=True,
    ).stdout.strip()

    if branch != VELXIO_BRANCH:
        raise BuildError(
            f"Velxio checkout is on '{branch}', expected '{VELXIO_BRANCH}'."
        )

    success("Velxio OSS checkout verified")


def compose(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run(
        [
            "docker",
            "compose",
            "-f",
            COMPOSE_FILE,
            "-p",
            COMPOSE_PROJECT,
            *args,
        ],
        cwd=root() / VELXIO_DIR,
        capture=capture,
    )


def wait_for_health(timeout: int = 180) -> bool:
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
                if 200 <= response.status < 300:
                    return True
        except Exception:
            pass

        time.sleep(2)

    return False


def health() -> None:
    log(f"Checking {HEALTH_URL}")

    if wait_for_health():
        success("Velxio OSS is healthy")
        return

    raise BuildError(
        "Velxio OSS did not become healthy within 180 seconds. "
        "Run: python3 build.py logs"
    )


def setup() -> None:
    log(f"IoT-Studio developer bootstrap {VERSION}")

    check_host()
    validate_provider_assets()
    clone_velxio()
    verify_velxio()
    sync_qemu()

    compose(["build"])
    success("Velxio OSS image built")

    compose(["up", "-d"])
    health()

    print()
    success("Developer setup complete")
    print("Open: http://localhost:3080")


def build(no_cache: bool = False) -> None:
    check_host()
    clone_velxio()
    verify_velxio()
    validate_provider_assets()
    sync_qemu()

    command = ["build"]
    if no_cache:
        command.append("--no-cache")

    compose(command)
    success("Velxio OSS image built")


def rebuild(no_cache: bool = False) -> None:
    build(no_cache=no_cache)
    compose(["up", "-d"])
    health()


def start() -> None:
    check_host()
    clone_velxio()
    verify_velxio()
    validate_provider_assets()
    sync_qemu()

    compose(["up", "-d"])
    health()


def stop() -> None:
    check_host()
    compose(["stop"])
    success("Velxio OSS stopped")


def restart() -> None:
    check_host()
    compose(["restart"])
    health()


def status() -> None:
    check_host()
    compose(["ps"])


def logs() -> None:
    check_host()
    compose(["logs", "--tail", "200"])


def qemu() -> None:
    validate_provider_assets()

    if not (root() / VELXIO_DIR / ".git").is_dir():
        clone_velxio()

    verify_velxio()
    sync_qemu()


def doctor() -> int:
    print(f"IoT-Studio / Velxio OSS doctor {VERSION}")
    print()

    failures = 0

    def test(name: str, function) -> None:
        nonlocal failures

        try:
            function()
            success(name)
        except Exception as exc:
            failures += 1
            error(f"{name}: {exc}")

    test("Host prerequisites", check_host)
    test("IoT-Studio QEMU assets", validate_provider_assets)
    test("Velxio OSS checkout", lambda: (clone_velxio(), verify_velxio()))
    test("QEMU synchronization", sync_qemu)

    def compose_config() -> None:
        result = compose(["config"], capture=True, check=False)
        if result.returncode != 0:
            raise BuildError("Docker Compose configuration is invalid.")

    test("Docker Compose configuration", compose_config)

    def health_check() -> None:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
            if not 200 <= response.status < 300:
                raise BuildError(f"HTTP {response.status}")

    test("Velxio health endpoint", health_check)

    print()

    if failures:
        error(f"Doctor found {failures} problem(s)")
        return 1

    success("Doctor found no problems")
    return 0


def clean(volumes: bool = False) -> None:
    check_host()

    command = ["down", "--remove-orphans"]
    if volumes:
        warning(
            "Removing only the Velxio OSS project's named Docker volumes."
        )
        command.append("--volumes")

    compose(command)
    success("Velxio OSS Docker resources cleaned")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-command IoT-Studio developer setup for Velxio OSS."
    )

    parser.add_argument(
        "--version",
        action="version",
        version=VERSION,
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "setup",
        help="Full developer setup: Velxio + QEMU + Docker + start.",
    )
    sub.add_parser("build", help="Build the Velxio OSS Docker image.")
    sub.add_parser("start", help="Start Velxio OSS.")
    sub.add_parser("stop", help="Stop Velxio OSS.")
    sub.add_parser("restart", help="Restart Velxio OSS.")
    sub.add_parser("status", help="Show Velxio Docker status.")
    sub.add_parser("logs", help="Show the latest Velxio container logs.")
    sub.add_parser("qemu", help="Synchronize IoT-Studio QEMU assets.")
    sub.add_parser("doctor", help="Diagnose the developer environment.")

    rebuild_parser = sub.add_parser(
        "rebuild",
        help="Rebuild the OSS image and restart it.",
    )
    rebuild_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Perform a clean Docker build without cache.",
    )

    build_parser = sub.choices["build"]
    build_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Perform a clean Docker build without cache.",
    )

    clean_parser = sub.add_parser(
        "clean",
        help="Remove this project's Docker resources only.",
    )
    clean_parser.add_argument(
        "--volumes",
        action="store_true",
        help="Also remove this project's named volumes.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = args.command or "setup"

    try:
        if command == "setup":
            setup()
        elif command == "build":
            build(no_cache=args.no_cache)
        elif command == "rebuild":
            rebuild(no_cache=args.no_cache)
        elif command == "start":
            start()
        elif command == "stop":
            stop()
        elif command == "restart":
            restart()
        elif command == "status":
            status()
        elif command == "logs":
            logs()
        elif command == "qemu":
            qemu()
        elif command == "doctor":
            return doctor()
        elif command == "clean":
            clean(volumes=args.volumes)
        else:
            raise BuildError(f"Unknown command: {command}")

        return 0

    except KeyboardInterrupt:
        warning("Interrupted")
        return 130

    except BuildError as exc:
        error(str(exc))
        return 1

    except subprocess.CalledProcessError as exc:
        error(f"Command failed with exit code {exc.returncode}")
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
