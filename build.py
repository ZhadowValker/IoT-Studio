#!/usr/bin/env python3
"""
Velxio OSS developer build orchestrator.

One-command developer setup/build flow:
    python3 build.py setup
    python3 build.py start
    python3 build.py rebuild
    python3 build.py doctor
    python3 build.py status
    python3 build.py restart
    python3 build.py stop
    python3 build.py qemu
    python3 build.py clean

This script intentionally does NOT:
- require GitHub CLI or a GitHub token
- change the developer's Git identity/configuration
- reset or discard Velxio source changes
- install or enable Velxio Pro
- download QEMU from velxio.dev

IoT-Studio is used only as the public QEMU asset provider.
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


SCRIPT_VERSION = "1.0.0-oss-one-command"

VELXIO_REPO = "https://github.com/ZhadowValker/velxio.git"
IOT_STUDIO_REPO = "https://github.com/ZhadowValker/IoT-Studio.git"

COMPOSE_FILE = "docker-compose.oss.yml"
COMPOSE_PROJECT = "velxio-oss"
CONTAINER_NAME = "velxio-oss"
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

# Keep provider tooling outside the Velxio repository so it cannot pollute
# the developer's source tree or accidentally become part of a commit.
DEFAULT_PROVIDER_DIR = Path.home() / ".cache" / "velxio" / "IoT-Studio"


class BuildError(RuntimeError):
    pass


def color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def info(message: str) -> None:
    print(f"{color('INFO', '36')}: {message}")


def ok(message: str) -> None:
    print(f"{color(' OK ', '32')}: {message}")


def warn(message: str) -> None:
    print(f"{color('WARN', '33')}: {message}")


def fail(message: str) -> None:
    print(f"{color('FAIL', '31')}: {message}")


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    info("$ " + " ".join(args))
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def provider_dir() -> Path:
    override = os.environ.get("VELXIO_IOT_STUDIO_DIR")
    return Path(override).expanduser().resolve() if override else DEFAULT_PROVIDER_DIR


def require_repo_root() -> None:
    root = repo_root()
    if not (root / ".git").exists():
        raise BuildError("build.py must be run from the Velxio Git repository root.")


def git_branch(root: Path) -> str:
    result = run(
        ["git", "branch", "--show-current"],
        cwd=root,
        capture=True,
    )
    return result.stdout.strip()


def verify_oss_tree(root: Path) -> None:
    missing = [path for path in REQUIRED_VELXIO_FILES if not (root / path).is_file()]
    if missing:
        raise BuildError(
            "This checkout does not contain the expected strict OSS build files:\n"
            + "\n".join(f"  - {p}" for p in missing)
        )

    branch = git_branch(root)
    if branch != "oss":
        raise BuildError(
            f"Current branch is '{branch or '(detached HEAD)'}'. "
            "The strict OSS build must be run from the 'oss' branch."
        )

    ok("Velxio OSS checkout verified")


def check_prerequisites() -> None:
    required = ["git", "docker", "curl", "python3"]
    missing = [name for name in required if not command_exists(name)]
    if missing:
        raise BuildError(
            "Missing required host commands: " + ", ".join(missing)
        )

    result = run(
        ["docker", "info"],
        check=False,
        capture=True,
    )
    if result.returncode != 0:
        raise BuildError(
            "Docker is installed but the Docker daemon is not reachable.\n"
            "Start Docker Desktop (or your Docker daemon) and run this command again."
        )

    result = run(
        ["docker", "compose", "version"],
        check=False,
        capture=True,
    )
    if result.returncode != 0:
        raise BuildError("Docker Compose v2 is required: 'docker compose' was not found.")

    ok("Host prerequisites verified")


def clone_or_update_provider(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not (path / ".git").is_dir():
        info(f"Cloning public IoT-Studio provider into {path}")
        run(["git", "clone", "--depth", "1", IOT_STUDIO_REPO, str(path)])
        ok("IoT-Studio provider cloned")
        return

    # Never overwrite a developer's local provider changes.
    status = run(
        ["git", "status", "--porcelain"],
        cwd=path,
        capture=True,
    ).stdout.strip()

    if status:
        warn(
            "IoT-Studio provider has local changes; leaving it untouched. "
            "The existing prebuilt assets will be used."
        )
        return

    info("Refreshing IoT-Studio provider")
    run(["git", "fetch", "--depth", "1", "origin", "main"], cwd=path)

    current = run(
        ["git", "branch", "--show-current"],
        cwd=path,
        capture=True,
    ).stdout.strip()

    if current != "main":
        run(["git", "switch", "main"], cwd=path)

    run(["git", "reset", "--hard", "origin/main"], cwd=path)
    ok("IoT-Studio provider refreshed")


def validate_qemu_file(path: Path) -> bool:
    if not path.is_file():
        return False

    try:
        size = path.stat().st_size
    except OSError:
        return False

    if size < 1024:
        return False

    if path.suffix == ".so":
        try:
            with path.open("rb") as handle:
                magic = handle.read(4)
            return magic == b"\x7fELF"
        except OSError:
            return False

    return True


def sync_qemu_assets(root: Path, provider: Path) -> None:
    source_dir = provider / "prebuilt"
    target_dir = root / "prebuilt" / "qemu"
    target_dir.mkdir(parents=True, exist_ok=True)

    missing = []
    copied = []

    for filename in QEMU_FILES:
        source = source_dir / filename
        target = target_dir / filename

        if not validate_qemu_file(source):
            missing.append(filename)
            continue

        # Copy only when missing or different. This makes repeated setup fast
        # and avoids unnecessary writes.
        should_copy = not target.exists()
        if not should_copy:
            try:
                should_copy = (
                    source.stat().st_size != target.stat().st_size
                    or source.stat().st_mtime_ns > target.stat().st_mtime_ns
                )
            except OSError:
                should_copy = True

        if should_copy:
            shutil.copy2(source, target)
            copied.append(filename)

    if missing:
        raise BuildError(
            "IoT-Studio does not contain all required QEMU assets in "
            f"{source_dir}:\n"
            + "\n".join(f"  - {name}" for name in missing)
        )

    if copied:
        ok("QEMU assets synchronized: " + ", ".join(copied))
    else:
        ok("QEMU assets already present and valid")

    # Final target-side validation.
    invalid = [
        name
        for name in QEMU_FILES
        if not validate_qemu_file(target_dir / name)
    ]
    if invalid:
        raise BuildError(
            "QEMU assets failed final validation:\n"
            + "\n".join(f"  - {name}" for name in invalid)
        )


def compose(root: Path, args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run(
        ["docker", "compose", "-f", COMPOSE_FILE, "-p", COMPOSE_PROJECT, *args],
        cwd=root,
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


def health_check() -> None:
    info(f"Checking {HEALTH_URL}")
    if wait_for_health():
        ok("Velxio OSS is healthy")
        return

    raise BuildError(
        f"Velxio did not become healthy within the timeout. "
        f"Check: docker compose -f {COMPOSE_FILE} logs"
    )


def build_image(root: Path, no_cache: bool = False) -> None:
    sync_provider_and_qemu(root)
    args = ["build"]
    if no_cache:
        args.append("--no-cache")
    compose(root, args)
    ok("Velxio OSS image built")


def start_service(root: Path, *, build: bool = False) -> None:
    if build:
        build_image(root)
    compose(root, ["up", "-d"])
    health_check()


def sync_provider_and_qemu(root: Path) -> None:
    provider = provider_dir()
    clone_or_update_provider(provider)
    sync_qemu_assets(root, provider)


def setup(root: Path) -> None:
    info(f"Velxio OSS developer setup {SCRIPT_VERSION}")
    check_prerequisites()
    verify_oss_tree(root)
    sync_provider_and_qemu(root)
    compose(root, ["build"])
    compose(root, ["up", "-d"])
    health_check()
    print()
    ok("Developer setup complete")
    print("Open: http://localhost:3080")


def qemu(root: Path) -> None:
    verify_oss_tree(root)
    check_prerequisites()
    sync_provider_and_qemu(root)


def rebuild(root: Path, no_cache: bool = False) -> None:
    check_prerequisites()
    verify_oss_tree(root)
    build_image(root, no_cache=no_cache)
    compose(root, ["up", "-d"])
    health_check()


def start(root: Path) -> None:
    check_prerequisites()
    verify_oss_tree(root)
    # If QEMU assets are missing, repair them automatically.
    sync_provider_and_qemu(root)
    compose(root, ["up", "-d"])
    health_check()


def restart(root: Path) -> None:
    check_prerequisites()
    verify_oss_tree(root)
    compose(root, ["restart"])
    health_check()


def stop(root: Path) -> None:
    check_prerequisites()
    compose(root, ["stop"])
    ok("Velxio OSS stopped")


def status(root: Path) -> None:
    check_prerequisites()
    compose(root, ["ps"])


def doctor(root: Path) -> int:
    print(f"Velxio OSS doctor {SCRIPT_VERSION}")
    print()

    failures = 0

    def test(label: str, fn) -> None:
        nonlocal failures
        try:
            fn()
            ok(label)
        except Exception as exc:
            failures += 1
            fail(f"{label}: {exc}")

    test("Repository root", lambda: require_repo_root())
    test("OSS branch", lambda: verify_oss_tree(root))
    test("Host prerequisites", check_prerequisites)
    test("QEMU provider/assets", lambda: sync_provider_and_qemu(root))

    def compose_config() -> None:
        result = compose(root, ["config"], capture=True)
        if result.returncode != 0:
            raise BuildError("docker compose configuration is invalid")

    test("Docker Compose configuration", compose_config)

    def health() -> None:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:
            if response.status < 200 or response.status >= 300:
                raise BuildError(f"HTTP {response.status}")

    test("Running health endpoint", health)

    print()
    if failures:
        fail(f"Doctor found {failures} problem(s)")
        return 1

    ok("Doctor found no problems")
    return 0


def clean(root: Path, volumes: bool = False) -> None:
    check_prerequisites()
    args = ["down", "--remove-orphans"]
    if volumes:
        warn("Removing project volumes: velxio-oss-build and velxio-oss-ccache")
        args.append("--volumes")
    compose(root, args)
    ok("Velxio OSS project resources cleaned")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-command developer setup/build tool for Velxio OSS."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=SCRIPT_VERSION,
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Set up provider, QEMU assets, build and start OSS.")
    sub.add_parser("qemu", help="Sync QEMU assets from IoT-Studio.")
    sub.add_parser("start", help="Start the OSS container and verify health.")
    sub.add_parser("restart", help="Restart the OSS container and verify health.")
    sub.add_parser("stop", help="Stop the OSS container.")
    sub.add_parser("status", help="Show Docker Compose status.")
    sub.add_parser("doctor", help="Validate developer environment and OSS runtime.")

    rebuild_parser = sub.add_parser("rebuild", help="Build the OSS image and restart it.")
    rebuild_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force a completely fresh Docker build.",
    )

    clean_parser = sub.add_parser(
        "clean",
        help="Remove this project's containers/networks (not global Docker resources).",
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
    root = repo_root()

    try:
        require_repo_root()

        if command == "setup":
            setup(root)
        elif command == "qemu":
            qemu(root)
        elif command == "start":
            start(root)
        elif command == "restart":
            restart(root)
        elif command == "stop":
            stop(root)
        elif command == "status":
            status(root)
        elif command == "doctor":
            return doctor(root)
        elif command == "rebuild":
            rebuild(root, no_cache=args.no_cache)
        elif command == "clean":
            clean(root, volumes=args.volumes)
        else:
            raise BuildError(f"Unknown command: {command}")

        return 0

    except KeyboardInterrupt:
        warn("Interrupted")
        return 130
    except BuildError as exc:
        fail(str(exc))
        return 1
    except subprocess.CalledProcessError as exc:
        fail(f"Command failed with exit code {exc.returncode}")
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
