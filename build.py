#!/usr/bin/env python3
"""
Velxio One-Command Downstream Bootstrapper
==========================================

Default behavior:
  python build.py

is the same as:
  python build.py bootstrap --profile full

It creates the upstream/downstream structure, obtains the OSS Velxio checkout,
installs/checks prerequisites, configures backend/frontend, installs Arduino
cores, and for full profile provisions ESP-IDF + native QEMU assets.

This file supports two build modes: strict OSS Docker and OSS Local Dev.
QEMU provider selection happens before either build mode starts.
"""
from __future__ import annotations
import argparse, contextlib, ctypes, datetime as _dt, hashlib, json, os, platform, shutil, signal, socket, subprocess, sys, time, urllib.request
from pathlib import Path
from typing import Any, Optional

SCRIPT_VERSION = "3.0.0-oss-dual-mode"
REPO_URL = "https://github.com/ZhadowValker/velxio.git"
VELXIO_BRANCH = "oss"
QEMU_RELEASE_BASE = "https://github.com/davidmonterocrespo24/velxio/releases/download/qemu-prebuilt"
ARDUINO_CLI_INSTALL_SCRIPT = "https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh"
RP2040_INDEX = "https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json"
ESP32_INDEX = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
ATTINY_INDEX = "http://drazzy.com/package_drazzy.com_index.json"
ESP_IDF_VERSION = "v4.4.7"
ARDUINO_ESP32_VERSION = "2.0.17"
SCRIPT_DIR = Path(__file__).resolve().parent
PRODUCT_ROOT = Path(os.environ.get("VELXIO_PRODUCT_ROOT", SCRIPT_DIR / "our-velxio")).resolve()
UPSTREAM_ROOT = PRODUCT_ROOT / "upstream"
UPSTREAM_DIR = UPSTREAM_ROOT / "velxio"
DOWNSTREAM_DIR = PRODUCT_ROOT / "downstream"
CONFIG_DIR = DOWNSTREAM_DIR / "config"
CACHE_DIR = DOWNSTREAM_DIR / "cache"
LIB_DIR = DOWNSTREAM_DIR / "lib"
LOG_DIR = DOWNSTREAM_DIR / "logs"
RUN_DIR = DOWNSTREAM_DIR / "run"
VALIDATION_DIR = DOWNSTREAM_DIR / "validation"
PATCH_DIR = DOWNSTREAM_DIR / "patches"
BACKEND_DIR = UPSTREAM_DIR / "backend"
FRONTEND_DIR = UPSTREAM_DIR / "frontend"
CONFIG_FILE = CONFIG_DIR / "velxio.json"
LOCK_FILE = DOWNSTREAM_DIR / "velxio.lock.json"
QEMU_MANIFEST_FILE = CONFIG_DIR / "qemu_manifest.json"
BACKEND_PORT = 8001
FRONTEND_PORT = 5173
PYTHON_MIN = (3, 12)
NODE_MIN_MAJOR = 18
PROFILES: dict[str, dict[str, Any]] = {
    "browser": {"description": "AVR + RP2040 development without native QEMU.", "cores": ["arduino:avr", "rp2040:rp2040"], "needs_espidf": False, "needs_qemu": False},
    "full": {"description": "Full local Velxio: browser boards + ESP32/ESP32-C3 native QEMU + ESP-IDF.", "cores": ["arduino:avr", "rp2040:rp2040", f"esp32:esp32@{ARDUINO_ESP32_VERSION}"], "needs_espidf": True, "needs_qemu": True},
}
QEMU_LIBS = ["libqemu-xtensa.so", "libqemu-riscv32.so"]
QEMU_ROMS = ["esp32-v3-rom.bin", "esp32-v3-rom-app.bin", "esp32c3-rom.bin", "esp32s3_rev0_rom.bin"]
QEMU_PREBUILT_DIR = SCRIPT_DIR / "prebuilt"
DOCKER_COMPOSE_FILE = "docker-compose.oss.yml"
DOCKER_PROJECT = "velxio-oss"
DOCKER_HEALTH_URL = "http://localhost:3080/health"
OSS_REQUIRED_FILES = ["Dockerfile.oss", "docker-compose.oss.yml", "frontend/vite.oss.config.ts", "frontend/scripts/build-oss.mjs"]
EXIT_OK, EXIT_FAIL, EXIT_PARTIAL = 0, 1, 2
class BuildError(RuntimeError): pass
class Log:
    def __init__(self, quiet: bool=False):
        self.quiet=quiet; LOG_DIR.mkdir(parents=True, exist_ok=True); self.logfile=LOG_DIR/"build.log"
    def _write(self, level, msg):
        ts=_dt.datetime.now().isoformat(timespec="seconds")
        with open(self.logfile,"a",encoding="utf-8") as f: f.write(f"{ts} [{level}] {msg}\n")
        if not self.quiet or level in {"FAIL","WARN"}: print(f"[{level}] {msg}")
    def step(self,m): self._write("STEP",m)
    def ok(self,m): self._write(" OK ",m)
    def info(self,m): self._write("INFO",m)
    def warn(self,m): self._write("WARN",m)
    def fail(self,m): self._write("FAIL",m)
    def skip(self,m): self._write("SKIP",m)
LOG=Log()
def ensure_dirs():
    for d in [PRODUCT_ROOT,UPSTREAM_ROOT,DOWNSTREAM_DIR,CONFIG_DIR,CACHE_DIR,LIB_DIR,LOG_DIR,RUN_DIR,VALIDATION_DIR,PATCH_DIR]: d.mkdir(parents=True,exist_ok=True)
def os_name():
    s=platform.system().lower()
    return "linux" if s.startswith("linux") else "macos" if s.startswith("darwin") else "windows" if s.startswith("windows") else s
def arch_name():
    m=platform.machine().lower()
    return "amd64" if m in ("x86_64","amd64") else "arm64" if m in ("aarch64","arm64") else m
def which(cmd): return shutil.which(cmd)
def run(cmd, cwd:Optional[Path]=None, check=True, capture=False, env:Optional[dict]=None, timeout:Optional[int]=None):
    LOG.info("$ "+" ".join(map(str,cmd))+(f"  (cwd={cwd})" if cwd else "")); merged={**os.environ,**(env or {})}
    try:
        return subprocess.run([str(c) for c in cmd],cwd=str(cwd) if cwd else None,env=merged,check=check,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.STDOUT if capture else None,timeout=timeout)
    except FileNotFoundError: raise BuildError(f"Command not found: {cmd[0]}")
    except subprocess.CalledProcessError as e:
        if capture and e.stdout: LOG.fail(e.stdout[-3000:])
        raise BuildError(f"Command failed with exit code {e.returncode}: {' '.join(cmd)}")
    except subprocess.TimeoutExpired: raise BuildError(f"Command timed out after {timeout}s: {' '.join(cmd)}")
def tcp_ok(host,port=443,timeout=4.0):
    try:
        with contextlib.closing(socket.create_connection((host,port),timeout=timeout)): return True
    except OSError: return False
def require_network(host="github.com"):
    if not tcp_ok(host): raise BuildError(f"Network check failed for {host}. Check internet/proxy and rerun.")
def download(url,dest:Path,retries=2,timeout=25):
    dest.parent.mkdir(parents=True,exist_ok=True); tmp=dest.with_suffix(dest.suffix+".part"); last=None
    for n in range(1,retries+1):
        try:
            LOG.info(f"download {url} -> {dest.name} attempt {n}/{retries}"); req=urllib.request.Request(url,headers={"User-Agent":"velxio-downstream-build/2.0"})
            with urllib.request.urlopen(req,timeout=timeout) as r, open(tmp,"wb") as f: shutil.copyfileobj(r,f)
            tmp.rename(dest); LOG.ok(f"downloaded {dest}"); return
        except Exception as e:
            last=e; LOG.warn(f"download failed: {e}"); tmp.unlink(missing_ok=True); time.sleep(n)
    raise BuildError(f"Failed to download {url}: {last}")
def sha256(path:Path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def save_config(profile,qemu_provider):
    CONFIG_FILE.write_text(json.dumps({"profile":profile,"qemu_provider":qemu_provider,"product_root":str(PRODUCT_ROOT),"upstream_dir":str(UPSTREAM_DIR),"downstream_dir":str(DOWNSTREAM_DIR),"backend_port":BACKEND_PORT,"frontend_port":FRONTEND_PORT,"updated":_dt.datetime.now().isoformat()},indent=2),encoding="utf-8")
def load_config():
    if CONFIG_FILE.exists():
        try: return json.loads(CONFIG_FILE.read_text())
        except Exception: pass
    return {"profile":"full","qemu_provider":"prebuilt","backend_port":BACKEND_PORT,"frontend_port":FRONTEND_PORT}


def ensure_velxio_runtime_dirs():
    """Create writable runtime/cache dirs used by Velxio manual full profile.

    Docker maps velxio-build to /var/lib/velxio-build.
    In manual WSL mode, this path may not exist or may be root-owned.
    ESP32 / ESP32-C3 compile fails with:
      Permission denied: '/var/lib/velxio-build'
    if the current user cannot write there.
    """
    LOG.step("Ensuring Velxio writable runtime directories")

    runtime_dirs = [
        "/var/lib/velxio-build",
        "/var/cache/ccache",
    ]

    for d in runtime_dirs:
        run(["sudo", "mkdir", "-p", d], check=False)
        run(["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", d], check=False)
        run(["chmod", "-R", "u+rwX", d], check=False)

    LOG.ok("Velxio runtime directories are writable")

def create_structure():
    LOG.step("Creating upstream + downstream folder structure"); ensure_dirs()
    (DOWNSTREAM_DIR/"README_DOWNSTREAM.md").write_text(f"""# Our Velxio Variant Downstream Layer

Formula:

```text
upstream/velxio + downstream/build.py + native provider = our Velxio variant
```

Folders:

```text
{PRODUCT_ROOT}/upstream/velxio       upstream source clone
{DOWNSTREAM_DIR}/cache               downloaded/build toolchains
{DOWNSTREAM_DIR}/lib                 QEMU .so files and ESP32 ROM blobs
{DOWNSTREAM_DIR}/config              generated env and config files
{DOWNSTREAM_DIR}/logs                setup and runtime logs
{DOWNSTREAM_DIR}/validation          reports
```
""",encoding="utf-8")
    LOG.ok(f"Structure ready at {PRODUCT_ROOT}")
def package_manager():
    if os_name()=="linux":
        for x in ["apt-get","dnf","yum","pacman"]:
            if which(x): return x
    if os_name()=="macos" and which("brew"): return "brew"
    if os_name()=="windows" and which("winget"): return "winget"
    return "unknown"
def install_os_packages(profile):
    LOG.step("Installing/checking OS prerequisites as first step"); pm=package_manager()
    if os_name()=="linux" and pm=="apt-get":
        pkgs=["git","curl","ca-certificates","python3","python3-venv","python3-pip","python3-full","python3-virtualenv","python-is-python3","nodejs","npm"]
        if profile=="full": pkgs += ["ninja-build","pkg-config","flex","bison","cmake","ccache","libglib2.0-dev","libpixman-1-dev","libglib2.0-0","libgcrypt20","libslirp0","libpixman-1-0","libfdt1","libusb-1.0-0"]
        run(["sudo","apt-get","update"],check=False); run(["sudo","apt-get","install","-y",*pkgs],check=False)
    elif os_name()=="linux" and pm=="pacman":
        pkgs=["git","curl","ca-certificates","python","python-pip","python-virtualenv","nodejs","npm"]
        if profile=="full": pkgs += ["ninja","pkgconf","flex","bison","cmake","ccache","glib2","pixman"]
        run(["sudo","pacman","-S","--needed","--noconfirm",*pkgs],check=False)
    elif os_name()=="macos" and pm=="brew":
        pkgs=["git","node","python@3.12"] + (["ninja","pkg-config","glib","pixman","cmake","ccache"] if profile=="full" else [])
        run(["brew","install",*pkgs],check=False)
    elif os_name()=="windows" and pm=="winget":
        for pkg in ["Git.Git","OpenJS.NodeJS","ArduinoSA.arduino-cli"]: run(["winget","install","--id",pkg,"-e","--silent"],check=False)
    else: LOG.warn("No supported OS package manager detected. Continuing with checks; missing tools will be reported.")
    lb=str(Path.home()/".local"/"bin")
    if lb not in os.environ.get("PATH",""): os.environ["PATH"]=lb+os.pathsep+os.environ.get("PATH","")
def clone_or_update_upstream(ref=VELXIO_BRANCH, force=False):
    LOG.step("Cloning or updating OSS Velxio")
    require_network("github.com")
    if not (UPSTREAM_DIR / ".git").exists():
        if UPSTREAM_DIR.exists() and any(UPSTREAM_DIR.iterdir()):
            raise BuildError(f"{UPSTREAM_DIR} exists but is not a valid Velxio Git checkout. Move it aside and run setup again.")
        run(["git", "clone", "--branch", VELXIO_BRANCH, REPO_URL, str(UPSTREAM_DIR)])
    else:
        status=run(["git","status","--porcelain"],cwd=UPSTREAM_DIR,capture=True,check=False)
        if status.returncode==0 and status.stdout.strip() and not force:
            LOG.warn("OSS Velxio has local changes. Not changing the checkout. Use --force if intentional.")
            return
        # Ensure origin points to the public OSS fork and use the OSS branch.
        rem=run(["git","remote","get-url","origin"],cwd=UPSTREAM_DIR,capture=True,check=False)
        current_remote=rem.stdout.strip() if rem.returncode==0 else ""
        if current_remote != REPO_URL:
            if current_remote:
                run(["git","remote","set-url","origin",REPO_URL],cwd=UPSTREAM_DIR)
            else:
                run(["git","remote","add","origin",REPO_URL],cwd=UPSTREAM_DIR)
        run(["git","fetch","origin",VELXIO_BRANCH],cwd=UPSTREAM_DIR)
        run(["git","checkout",VELXIO_BRANCH],cwd=UPSTREAM_DIR)
        run(["git","pull","--ff-only","origin",VELXIO_BRANCH],cwd=UPSTREAM_DIR,check=False)
    LOG.ok(f"OSS Velxio ready: {UPSTREAM_DIR}")

def venv_dir(): return BACKEND_DIR/"venv"
def venv_python(): return venv_dir()/("Scripts/python.exe" if os_name()=="windows" else "bin/python")
def venv_pip(): return venv_dir()/("Scripts/pip.exe" if os_name()=="windows" else "bin/pip")
def check_cmd(cmd,args=None):
    p=which(cmd)
    if not p: return False,"not found"
    if args:
        try:
            o=subprocess.run([cmd,*args],capture_output=True,text=True,timeout=10); line=(o.stdout or o.stderr).strip().splitlines()[0] if (o.stdout or o.stderr).strip() else ""; return True,f"{p} {line}"
        except Exception: pass
    return True,p
def qemu_loadable():
    p=LIB_DIR/"libqemu-xtensa.so"
    if not p.exists(): return False
    try: ctypes.CDLL(str(p)); return True
    except OSError: return False
def doctor(profile):
    LOG.step(f"Doctor checks for profile={profile}"); checks=[]
    checks += [("Python >= 3.12", sys.version_info>=PYTHON_MIN, sys.version.split()[0])]
    for c,a in [("git",["--version"]),("node",["--version"]),("npm",["--version"]),("arduino-cli",["version"] )]:
        ok,d=check_cmd(c,a); checks.append((c,ok,d))
    checks += [("upstream source",(BACKEND_DIR/"requirements.txt").exists() and (FRONTEND_DIR/"package.json").exists(),str(UPSTREAM_DIR)),("backend venv",venv_python().exists(),str(venv_python())),("frontend node_modules",(FRONTEND_DIR/"node_modules").exists(),str(FRONTEND_DIR/"node_modules"))]
    if profile=="full":
        for f in QEMU_LIBS+QEMU_ROMS: checks.append((f,(LIB_DIR/f).exists(),str(LIB_DIR/f)))
        checks += [("IDF_PATH env file",(CONFIG_DIR/"espidf.env").exists(),str(CONFIG_DIR/"espidf.env")),("QEMU env file",(CONFIG_DIR/"qemu.env").exists(),str(CONFIG_DIR/"qemu.env")),("QEMU ctypes load",qemu_loadable(),"ctypes.CDLL(libqemu-xtensa.so)")]
    all_ok=True
    for n,ok,d in checks: all_ok=all_ok and ok; (LOG.ok if ok else LOG.warn)(f"{n}: {d}")
    return all_ok
def setup_backend():
    LOG.step("Setting backend prerequisites")
    if not (BACKEND_DIR/"requirements.txt").exists(): raise BuildError("backend/requirements.txt missing after clone")
    if not venv_python().exists(): run([sys.executable,"-m","venv",str(venv_dir())])
    run([str(venv_pip()),"install","--upgrade","pip"]); run([str(venv_pip()),"install","-r","requirements.txt"],cwd=BACKEND_DIR); LOG.ok("Backend ready")


def ensure_frontend_root_tools():
    """Install repo-root frontend helper tools needed by npm run dev.

    frontend/package.json runs:
      cd .. && npx tsx scripts/generate-component-metadata.ts

    Because this runs from the upstream repo root, tsx must be available there.
    If tsx is missing, npx asks:
      Ok to proceed? (y)

    Since build.py starts frontend in the background, that prompt blocks startup.
    """
    LOG.step("Ensuring frontend generator tools at upstream repo root")
    if not (UPSTREAM_DIR / "package.json").exists():
        (UPSTREAM_DIR / "package.json").write_text(
            '{"private":true,"devDependencies":{}}\n',
            encoding="utf-8"
        )
    run(["npm", "install", "--save-dev", "tsx"], cwd=UPSTREAM_DIR)
    LOG.ok("Frontend generator tool tsx is ready at upstream repo root")

def setup_frontend():
    LOG.step("Setting frontend prerequisites")
    if not (FRONTEND_DIR/"package.json").exists(): raise BuildError("frontend/package.json missing after clone")
    run(["npm","ci"] if (FRONTEND_DIR/"package-lock.json").exists() else ["npm","install"],cwd=FRONTEND_DIR); ensure_frontend_root_tools(); LOG.ok("Frontend ready")
def ensure_arduino_cli():
    LOG.step("Ensuring arduino-cli")
    if which("arduino-cli"): LOG.ok("arduino-cli already installed"); return
    if os_name()=="windows": run(["winget","install","--id","ArduinoSA.arduino-cli","-e","--silent"],check=False)
    else:
        require_network("raw.githubusercontent.com"); installer=CACHE_DIR/"install-arduino-cli.sh"; download(ARDUINO_CLI_INSTALL_SCRIPT,installer); bindir=Path.home()/".local"/"bin"; bindir.mkdir(parents=True,exist_ok=True); run(["sh",str(installer)],env={"BINDIR":str(bindir)}); os.environ["PATH"]=str(bindir)+os.pathsep+os.environ.get("PATH","")
    if not which("arduino-cli"): raise BuildError("arduino-cli still missing after install attempt")
def setup_arduino_cores(profile):
    LOG.step("Setting Arduino board cores"); ensure_arduino_cli(); run(["arduino-cli","core","update-index"]); run(["arduino-cli","core","install","arduino:avr"])
    run(["arduino-cli","config","add","board_manager.additional_urls",RP2040_INDEX],check=False); run(["arduino-cli","core","update-index"]); run(["arduino-cli","core","install","rp2040:rp2040"])
    run(["arduino-cli","config","add","board_manager.additional_urls",ATTINY_INDEX],check=False); run(["arduino-cli","core","update-index"]); run(["arduino-cli","core","install","ATTinyCore:avr"],check=False)
    if profile=="full":
        run(["arduino-cli","config","add","board_manager.additional_urls",ESP32_INDEX],check=False); run(["arduino-cli","core","update-index"]); run(["arduino-cli","core","install",f"esp32:esp32@{ARDUINO_ESP32_VERSION}"])
    LOG.ok("Arduino cores ready")


def ensure_espidf_python_prereqs():
    """Ubuntu 24.04 / Python 3.12 self-heal for ESP-IDF v4.4.7.

    ESP-IDF v4.4.7 install.sh calls idf_tools.py. If Python virtualenv is
    missing, idf_tools.py tries `python3 -m pip install --user virtualenv`.
    On Ubuntu 24.04 this fails because Python is externally managed (PEP 668).
    Installing distro packages first prevents that pip --user failure.
    """
    if os_name()=="linux" and which("apt-get"):
        run(["sudo","apt-get","install","-y","python3-full","python3-virtualenv","python-is-python3"],check=False)

def setup_espidf():
    LOG.step("Setting ESP-IDF prerequisites"); require_network("github.com"); idf=CACHE_DIR/"esp-idf"; arduino=CACHE_DIR/"arduino-esp32"
    if not idf.exists(): run(["git","clone","-b",ESP_IDF_VERSION,"--recursive","--depth=1","--shallow-submodules","https://github.com/espressif/esp-idf.git",str(idf)])
    else: LOG.skip("ESP-IDF already cloned")
    ensure_espidf_python_prereqs(); installer=idf/("install.bat" if os_name()=="windows" else "install.sh")
    try:
        run([str(installer),"esp32,esp32c3"],cwd=idf)
    except BuildError:
        LOG.warn("ESP-IDF install failed once. Applying Ubuntu/Python virtualenv self-heal and retrying.")
        ensure_espidf_python_prereqs()
        run([str(installer),"esp32,esp32c3"],cwd=idf)
    if not arduino.exists(): run(["git","clone","--branch",ARDUINO_ESP32_VERSION,"--depth=1","--recursive","--shallow-submodules","https://github.com/espressif/arduino-esp32.git",str(arduino)])
    (CONFIG_DIR/"espidf.env").write_text(f'export IDF_PATH="{idf}"\nexport IDF_TOOLS_PATH="{Path.home()/".espressif"}"\nexport ARDUINO_ESP32_PATH="{arduino}"\n',encoding="utf-8"); LOG.ok("ESP-IDF ready")
def setup_qemu_prebuilt():
    LOG.step("Setting native QEMU .so and ROM prerequisites"); require_network("github.com"); arch=arch_name()
    for lib in QEMU_LIBS:
        dest=LIB_DIR/lib
        if dest.exists(): LOG.skip(f"{lib} already exists"); continue
        base=lib[:-3] if lib.endswith(".so") else lib; download(f"{QEMU_RELEASE_BASE}/{base}-{arch}.so",dest)
    for rom in QEMU_ROMS:
        dest=LIB_DIR/rom
        if dest.exists(): LOG.skip(f"{rom} already exists"); continue
        download(f"{QEMU_RELEASE_BASE}/{rom}",dest)
    write_qemu_env(); LOG.ok("QEMU native files ready")

def validate_iot_studio_prebuilt():
    LOG.step("Validating IoT-Studio prebuilt QEMU assets")
    missing=[]; invalid=[]
    for name in QEMU_LIBS + QEMU_ROMS:
        src=QEMU_PREBUILT_DIR / name
        if not src.is_file():
            missing.append(name); continue
        if src.stat().st_size < 1024:
            invalid.append(name); continue
        if src.suffix == ".so":
            with open(src,"rb") as f:
                if f.read(4) != b"\x7fELF": invalid.append(name)
    if missing: raise BuildError("IoT-Studio prebuilt/ is missing: " + ", ".join(missing))
    if invalid: raise BuildError("Invalid IoT-Studio QEMU prebuilt asset(s): " + ", ".join(invalid))
    LOG.ok("All six IoT-Studio QEMU prebuilt assets verified")

def setup_qemu_prebuilt_local():
    """Use the authoritative IoT-Studio/prebuilt QEMU assets for Local Dev."""
    validate_iot_studio_prebuilt()
    LOG.step("Installing prebuilt QEMU into downstream/lib")
    for name in QEMU_LIBS + QEMU_ROMS:
        src=QEMU_PREBUILT_DIR / name
        dest=LIB_DIR / name
        shutil.copy2(src,dest)
        LOG.ok(f"Installed {name}")
    write_qemu_env()
    LOG.ok("Prebuilt QEMU files ready for Local Dev")

def install_qemu_build_deps():
    if os_name()=="linux" and which("apt-get"):
        run(["sudo","apt-get","update"],check=False); run(["sudo","apt-get","install","-y","git","ninja-build","pkg-config","libglib2.0-dev","libpixman-1-dev","python3","python3-venv","python3-pip","flex","bison"],check=False)
    elif os_name()=="macos" and which("brew"): run(["brew","install","ninja","pkg-config","glib","pixman"],check=False)
    else: LOG.warn("Could not auto-install source-build dependencies.")
def setup_qemu_source():
    LOG.step("Building QEMU native .so files from source using lcgamboa build script")
    require_network("github.com")

    qemu = CACHE_DIR / "qemu-lcgamboa"

    if qemu.exists():
        LOG.warn("Removing existing qemu-lcgamboa because it may be on the wrong branch")
        shutil.rmtree(qemu)

    run([
        "git", "clone",
        "--depth=1",
        "--branch", "picsimlab-esp32",
        "https://github.com/lcgamboa/qemu.git",
        str(qemu)
    ])

    install_qemu_build_deps()

    build_script = qemu / "build_libqemu-esp32.sh"
    if not build_script.exists():
        raise BuildError(f"Missing expected QEMU build script: {build_script}")

    run(["bash", str(build_script)], cwd=qemu)

    built = qemu / "build"

    xtensa = built / "libqemu-xtensa.so"
    riscv = built / "libqemu-riscv32.so"

    if not xtensa.exists():
        raise BuildError(f"Expected output missing: {xtensa}")

    shutil.copy2(xtensa, LIB_DIR / "libqemu-xtensa.so")

    if riscv.exists():
        shutil.copy2(riscv, LIB_DIR / "libqemu-riscv32.so")
    else:
        LOG.warn("libqemu-riscv32.so was not produced by build_libqemu-esp32.sh")
        LOG.warn("ESP32-C3 may not work until libqemu-riscv32.so is provided")

    for rom in QEMU_ROMS:
        src = qemu / "pc-bios" / rom
        if src.exists():
            shutil.copy2(src, LIB_DIR / rom)
        else:
            LOG.warn(f"ROM not found in qemu pc-bios: {rom}")

    write_qemu_env()
    LOG.ok("QEMU source build complete")


def write_qemu_env():
    (CONFIG_DIR/"qemu.env").write_text(f'export QEMU_ESP32_LIB="{LIB_DIR/"libqemu-xtensa.so"}"\nexport QEMU_RISCV32_LIB="{LIB_DIR/"libqemu-riscv32.so"}"\n',encoding="utf-8")
def backend_import_ok():
    if not venv_python().exists(): return False
    p=subprocess.run([str(venv_python()),"-c","import app.main"],cwd=BACKEND_DIR,text=True,capture_output=True)
    if p.returncode!=0: LOG.warn((p.stdout+p.stderr)[-1000:])
    return p.returncode==0
def validate(profile):
    LOG.step("Validating environment"); ok=doctor(profile); ok=backend_import_ok() and ok
    (LOG.ok if ok else LOG.warn)("Validation passed" if ok else "Validation has failures. Review logs above."); return ok
def smoke(profile):
    LOG.step("Running compile smoke checks")
    if not which("arduino-cli"): LOG.warn("arduino-cli missing"); return False
    work=CACHE_DIR/"smoke"; work.mkdir(parents=True,exist_ok=True)
    def make(name):
        d=work/name; d.mkdir(exist_ok=True); (d/f"{name}.ino").write_text("void setup(){pinMode(LED_BUILTIN,OUTPUT);} void loop(){digitalWrite(LED_BUILTIN,HIGH);delay(100);digitalWrite(LED_BUILTIN,LOW);delay(100);}\n"); return d
    tests=[("arduino:avr:uno",make("uno_blink")),("rp2040:rp2040:rpipico",make("pico_blink"))]
    if profile=="full": tests.append(("esp32:esp32:esp32:FlashMode=dio",make("esp32_blink")))
    ok=True
    for fqbn,folder in tests:
        p=subprocess.run(["arduino-cli","compile","--fqbn",fqbn,str(folder)],capture_output=True,text=True,timeout=300)
        if p.returncode==0: LOG.ok(f"compiled {fqbn}")
        else: ok=False; LOG.warn(f"compile failed {fqbn}: {(p.stdout+p.stderr)[-1000:]}")
    return ok


def load_espidf_export_env(env):
    """Merge ESP-IDF export.sh environment into backend runtime env.

    ESP-IDF install.sh creates toolchain paths and a Python virtual env.
    The backend ESP-IDF compiler must run with the same environment that:
      . $IDF_PATH/export.sh
    would provide.

    Without this, ESP-IDF CMake uses /usr/bin/python and fails with:
      IDF_PYTHON_ENV_PATH: (not set)
      Python interpreter used: /usr/bin/python
      Some Python dependencies must be installed
    """
    idf_path = env.get("IDF_PATH") or str(CACHE_DIR / "esp-idf")
    export_sh = Path(idf_path) / "export.sh"

    if not export_sh.exists():
        LOG.warn(f"ESP-IDF export.sh not found: {export_sh}")
        return env

    cmd = f'source "{export_sh}" >/dev/null 2>&1 && env'

    try:
        result = subprocess.run(
            ["bash", "-lc", cmd],
            text=True,
            capture_output=True,
            check=True,
        )
    except Exception as e:
        LOG.warn(f"Could not load ESP-IDF export environment: {e}")
        return env

    merged = dict(env)
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        merged[key] = value

    if "IDF_PYTHON_ENV_PATH" in merged:
        LOG.ok(f"ESP-IDF Python env: {merged['IDF_PYTHON_ENV_PATH']}")
    else:
        LOG.warn("ESP-IDF export loaded, but IDF_PYTHON_ENV_PATH is still not set")

    return merged

def service_env():
    env=dict(os.environ)
    for file in [CONFIG_DIR/"qemu.env",CONFIG_DIR/"espidf.env"]:
        if file.exists():
            for line in file.read_text().splitlines():
                line=line.strip(); line=line[7:] if line.startswith("export ") else line
                if "=" in line:
                    k,v=line.split("=",1); env[k]=v.strip('"')
    env = load_espidf_export_env(env)
    return env
def pidfile(name): return RUN_DIR/f"{name}.pid"
def is_running(name):
    pf=pidfile(name)
    if not pf.exists(): return False
    try: pid=int(pf.read_text().strip())
    except ValueError: return False
    try: os.kill(pid,0); return True
    except OSError: return False
def start_service(name,cmd,cwd,env=None):
    if is_running(name): LOG.skip(f"{name} already running"); return
    RUN_DIR.mkdir(parents=True,exist_ok=True); log=LOG_DIR/f"{name}.out.log"
    with open(log,"ab") as out: p=subprocess.Popen(cmd,cwd=str(cwd),stdout=out,stderr=subprocess.STDOUT,env=env or os.environ,start_new_session=(os_name()!="windows"))
    pidfile(name).write_text(str(p.pid)); LOG.ok(f"started {name} pid={p.pid}, log={log}")
def stop_service(name):
    pf=pidfile(name)
    if not is_running(name): LOG.skip(f"{name} not running"); pf.unlink(missing_ok=True); return
    pid=int(pf.read_text().strip())
    try:
        if os_name()=="windows": run(["taskkill","/PID",str(pid),"/F","/T"],check=False)
        else: os.killpg(os.getpgid(pid),signal.SIGTERM)
    finally: pf.unlink(missing_ok=True)
    LOG.ok(f"stopped {name}")
def start():
    ensure_velxio_runtime_dirs()
    LOG.step("Starting backend and frontend"); start_service("backend",[str(venv_python()),"-m","uvicorn","app.main:app","--port",str(BACKEND_PORT)],BACKEND_DIR,service_env()); frontend_env=dict(os.environ); frontend_env["npm_config_yes"]="true"; frontend_env["CI"]="true"; start_service("frontend",[which("npm") or "npm","run","dev","--","--port",str(FRONTEND_PORT)],FRONTEND_DIR,frontend_env); LOG.ok(f"Backend:  http://127.0.0.1:{BACKEND_PORT}"); LOG.ok(f"Frontend: http://127.0.0.1:{FRONTEND_PORT}")
def stop(): stop_service("backend"); stop_service("frontend")
def write_lock(profile,qemu_provider):
    commit=None
    if (UPSTREAM_DIR/".git").exists():
        p=subprocess.run(["git","rev-parse","HEAD"],cwd=UPSTREAM_DIR,text=True,capture_output=True); commit=p.stdout.strip() if p.returncode==0 else None
    data={"generated":_dt.datetime.now().isoformat(),"script_version":SCRIPT_VERSION,"profile":profile,"qemu_provider":qemu_provider,"product_root":str(PRODUCT_ROOT),"upstream_commit":commit,"python":sys.version,"os":os_name(),"arch":arch_name(),"files":{p.name:sha256(p) for p in LIB_DIR.glob("*") if p.is_file()}}
    LOCK_FILE.write_text(json.dumps(data,indent=2),encoding="utf-8"); LOG.ok(f"wrote {LOCK_FILE}")
def write_report(profile):
    report=VALIDATION_DIR/"full_profile_report.md"; report.write_text(f"""# Velxio Setup Report

Generated: {_dt.datetime.now().isoformat()}
Profile: `{profile}`

## Structure

```text
{PRODUCT_ROOT}/
  upstream/velxio/
  downstream/
    config/
    cache/
    lib/
    logs/
    validation/
```

## Run

```bash
python build.py start
```
""",encoding="utf-8"); LOG.ok(f"wrote {report}")
def bootstrap(profile,qemu_provider,start_after=False,smoke_after=False,force=False):
    if profile not in PROFILES: raise BuildError(f"Unknown profile: {profile}")
    if qemu_provider not in {"prebuilt","source"}: raise BuildError(f"Unknown QEMU provider: {qemu_provider}")
    # The provider decision is made before any Local Dev build/setup work.
    if profile == "full" and qemu_provider == "prebuilt":
        validate_iot_studio_prebuilt()
    create_structure(); save_config(profile,qemu_provider); ensure_velxio_runtime_dirs(); install_os_packages(profile); clone_or_update_upstream(force=force); setup_backend(); setup_frontend(); setup_arduino_cores(profile)
    if profile=="full": setup_espidf(); setup_qemu_source() if qemu_provider=="source" else setup_qemu_prebuilt_local()
    valid=validate(profile)
    if smoke_after: smoke(profile)
    write_lock(profile,qemu_provider); write_report(profile)
    if start_after: start()
    return EXIT_OK if valid else EXIT_PARTIAL
def plan(profile):
    LOG.step(f"Plan for profile={profile}"); steps=["Select and validate the QEMU provider before build/setup begins","Create our-velxio/upstream and our-velxio/downstream structure","Install/check OS prerequisites using apt/brew/pacman/winget when available","Clone or update OSS Velxio from ZhadowValker/velxio (oss branch)","Create backend Python venv and install requirements.txt","Install frontend npm dependencies","Install arduino-cli if missing","Install Arduino AVR and RP2040 cores"]
    if profile=="full": steps += ["Install ESP32 Arduino core 2.0.17","Clone/install ESP-IDF v4.4.7 for esp32 and esp32c3","Provision libqemu-xtensa.so, libqemu-riscv32.so, and ESP32 ROM blobs","Generate qemu.env and espidf.env"]
    steps += ["Run validation","Write lock file","Write setup report"]
    for i,s in enumerate(steps,1): print(f"{i}. {s}")

# ============================================================
# Docker / Strict OSS mode
# ============================================================

DOCKER_COMPOSE_FILE = "docker-compose.oss.yml"
DOCKER_PROJECT = "velxio-oss"
DOCKER_HEALTH_URL = "http://localhost:3080/health"
OSS_REQUIRED_FILES = [
    "Dockerfile.oss",
    "docker-compose.oss.yml",
    "frontend/vite.oss.config.ts",
    "frontend/scripts/build-oss.mjs",
]


def docker_check_host():
    missing=[c for c in ("git","docker","python3","curl") if not which(c)]
    if missing:
        raise BuildError("Missing required commands: " + ", ".join(missing))
    r=run(["docker","info"],capture=True,check=False)
    if r.returncode != 0:
        raise BuildError("Docker is installed but the Docker daemon is not available. Start Docker and try again.")
    r=run(["docker","compose","version"],capture=True,check=False)
    if r.returncode != 0:
        raise BuildError("Docker Compose v2 is required.")
    LOG.ok("Docker host prerequisites verified")


def verify_oss_source():
    for rel in OSS_REQUIRED_FILES:
        if not (UPSTREAM_DIR / rel).is_file():
            raise BuildError(f"OSS Velxio checkout is missing required file: {rel}")
    if not (UPSTREAM_DIR / ".git").is_dir():
        raise BuildError(f"OSS Velxio checkout missing Git metadata: {UPSTREAM_DIR}")
    branch=run(["git","branch","--show-current"],cwd=UPSTREAM_DIR,capture=True).stdout.strip()
    if branch != VELXIO_BRANCH:
        raise BuildError(f"Velxio checkout is on '{branch or 'detached HEAD'}', expected '{VELXIO_BRANCH}'.")
    LOG.ok("Velxio OSS source verified")


def docker_sync_qemu():
    validate_iot_studio_prebuilt()
    target=UPSTREAM_DIR / "prebuilt" / "qemu"
    target.mkdir(parents=True,exist_ok=True)
    for name in QEMU_LIBS + QEMU_ROMS:
        shutil.copy2(QEMU_PREBUILT_DIR / name, target / name)
    LOG.ok(f"Six QEMU prebuilt assets staged at {target}")


def docker_compose(args, *, capture=False, check=True):
    return run(
        ["docker","compose","-f",DOCKER_COMPOSE_FILE,"-p",DOCKER_PROJECT,*args],
        cwd=UPSTREAM_DIR,
        capture=capture,
        check=check,
    )


def docker_wait_for_health(timeout=180):
    deadline=time.time()+timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(DOCKER_HEALTH_URL,timeout=3) as response:
                if 200 <= response.status < 300:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def docker_health():
    LOG.step(f"Checking {DOCKER_HEALTH_URL}")
    if docker_wait_for_health():
        LOG.ok("Velxio OSS Docker service is healthy")
        return
    raise BuildError("Velxio OSS did not become healthy within 180 seconds. Run: python3 build.py docker-logs")


def docker_prepare():
    # Prebuilt is mandatory for Docker and is validated before Docker/build work.
    validate_iot_studio_prebuilt()
    docker_check_host()
    create_structure()
    clone_or_update_upstream()
    verify_oss_source()
    docker_sync_qemu()


def docker_setup():
    docker_prepare()
    docker_compose(["build"])
    LOG.ok("Velxio OSS Docker image built")
    docker_compose(["up","-d"])
    docker_health()
    print("\nVelxio OSS is available at http://localhost:3080")


def docker_build(no_cache=False):
    docker_prepare()
    cmd=["build"]
    if no_cache: cmd.append("--no-cache")
    docker_compose(cmd)
    LOG.ok("Velxio OSS Docker image built")


def docker_rebuild(no_cache=False):
    docker_build(no_cache=no_cache)
    docker_compose(["up","-d"])
    docker_health()


def docker_start():
    docker_prepare()
    docker_compose(["up","-d"])
    docker_health()


def docker_stop():
    docker_check_host()
    if not UPSTREAM_DIR.is_dir():
        LOG.skip("OSS Velxio checkout does not exist; nothing to stop")
        return
    docker_compose(["stop"])
    LOG.ok("Velxio OSS stopped")


def docker_restart():
    docker_check_host()
    verify_oss_source()
    docker_compose(["restart"])
    docker_health()


def docker_status():
    docker_check_host()
    verify_oss_source()
    docker_compose(["ps"])


def docker_logs():
    docker_check_host()
    verify_oss_source()
    docker_compose(["logs","--tail","200"])


def docker_qemu():
    # QEMU is always the IoT-Studio prebuilt provider in Docker mode.
    validate_iot_studio_prebuilt()
    clone_or_update_upstream()
    verify_oss_source()
    docker_sync_qemu()


def docker_doctor():
    print(f"IoT-Studio / Velxio OSS Docker doctor {SCRIPT_VERSION}\n")
    failures=0
    def test(name, fn):
        nonlocal failures
        try:
            fn(); LOG.ok(name)
        except Exception as exc:
            failures += 1; LOG.warn(f"{name}: {exc}")
    test("IoT-Studio QEMU assets", validate_iot_studio_prebuilt)
    test("Docker host", docker_check_host)
    test("OSS Velxio checkout", lambda: (clone_or_update_upstream(), verify_oss_source()))
    test("QEMU synchronization", docker_sync_qemu)
    def compose_config():
        r=docker_compose(["config"],capture=True,check=False)
        if r.returncode != 0: raise BuildError("Docker Compose configuration is invalid.")
    test("Docker Compose configuration", compose_config)
    def health_check():
        with urllib.request.urlopen(DOCKER_HEALTH_URL,timeout=3) as response:
            if not 200 <= response.status < 300: raise BuildError(f"HTTP {response.status}")
    test("Velxio health endpoint", health_check)
    if failures:
        error(f"Docker doctor found {failures} problem(s)")
        return EXIT_FAIL
    success("Docker doctor found no problems")
    return EXIT_OK


def docker_clean(volumes=False):
    docker_check_host()
    if not UPSTREAM_DIR.is_dir():
        LOG.skip("OSS Velxio checkout does not exist; nothing to clean")
        return
    cmd=["down","--remove-orphans"]
    if volumes:
        LOG.warn("Removing only the Velxio OSS project's named Docker volumes")
        cmd.append("--volumes")
    docker_compose(cmd)
    LOG.ok("Velxio OSS Docker resources cleaned")


def choose_qemu_provider():
    while True:
        print("\n============================================================")
        print(" IoT-Studio QEMU Provider")
        print("============================================================")
        print("  1. Prebuilt QEMU (IoT-Studio/prebuilt)")
        print("  2. Build QEMU from source (Local Dev only)")
        print("  3. Exit")
        choice=input("\nSelect QEMU provider: ").strip()
        if choice == "1":
            validate_iot_studio_prebuilt()
            return "prebuilt"
        if choice == "2":
            print("\nQEMU source build selected. This is available for Local Dev only.")
            return "source"
        if choice == "3":
            return None
        print("Invalid selection. Please choose 1, 2, or 3.")


def choose_build_mode(qemu_provider):
    while True:
        print("\n============================================================")
        print(" IoT-Studio Build Mode")
        print("============================================================")
        print("  1. Docker - Strict OSS")
        print("  2. Local Dev - OSS")
        print("  3. Back")
        choice=input("\nSelect build mode: ").strip()
        if choice == "1":
            if qemu_provider != "prebuilt":
                print("\nDocker Strict OSS requires IoT-Studio prebuilt QEMU. Please go back and select Prebuilt QEMU.")
                continue
            return "docker"
        if choice == "2": return "local"
        if choice == "3": return None
        print("Invalid selection. Please choose 1, 2, or 3.")


def interactive_main():
    print("\n============================================================")
    print(" IoT-Studio Developer Build")
    print(" Velxio OSS - Dual Mode")
    print("============================================================")
    print("QEMU provider is selected and validated before the build starts.")
    qemu_provider=choose_qemu_provider()
    if not qemu_provider:
        return EXIT_OK
    mode=choose_build_mode(qemu_provider)
    if not mode:
        return interactive_main()
    if mode == "docker":
        docker_setup()
        return EXIT_OK
    # Preserve the legacy full local flow, now against OSS Velxio and the selected provider.
    return bootstrap("full",qemu_provider)


def build_parser():
    p=argparse.ArgumentParser(description="IoT-Studio master builder: Velxio OSS Docker or Local Dev")
    p.add_argument("--version",action="version",version=SCRIPT_VERSION)
    sub=p.add_subparsers(dest="command")

    # Explicit top-level mode commands.
    for name, help_text in [("docker","Strict OSS Docker setup"),("local","OSS Local Dev setup")]:
        sp=sub.add_parser(name,help=help_text)
        sp.add_argument("--qemu-provider",choices=["prebuilt","source"],default="prebuilt")
        if name == "docker":
            sp.add_argument("--no-cache",action="store_true")
        else:
            sp.add_argument("--profile",choices=list(PROFILES),default="full")
            sp.add_argument("--start",action="store_true")
            sp.add_argument("--smoke",action="store_true")
            sp.add_argument("--force",action="store_true")

    # Docker lifecycle commands. Docker is always prebuilt-QEMU.
    for name, help_text in [
        ("docker-build","Build the strict OSS Docker image"),
        ("docker-rebuild","Rebuild and restart the strict OSS Docker image"),
        ("docker-start","Start strict OSS Docker"),
        ("docker-stop","Stop strict OSS Docker"),
        ("docker-restart","Restart strict OSS Docker"),
        ("docker-status","Show strict OSS Docker status"),
        ("docker-logs","Show strict OSS Docker logs"),
        ("docker-qemu","Validate and stage the IoT-Studio QEMU prebuilts"),
        ("docker-doctor","Diagnose the strict OSS Docker environment"),
    ]:
        sp=sub.add_parser(name,help=help_text)
        if name in {"docker-build","docker-rebuild"}: sp.add_argument("--no-cache",action="store_true")
    sp=sub.add_parser("docker-clean",help="Remove only the strict OSS Docker project resources")
    sp.add_argument("--volumes",action="store_true")

    # Original Local Dev CLI compatibility.
    sp=sub.add_parser("bootstrap",help="Legacy Local Dev bootstrap, now using OSS Velxio")
    sp.add_argument("--profile",choices=list(PROFILES),default="full")
    sp.add_argument("--qemu-provider",choices=["prebuilt","source"],default="prebuilt")
    sp.add_argument("--start",action="store_true"); sp.add_argument("--smoke",action="store_true"); sp.add_argument("--force",action="store_true")
    sp=sub.add_parser("plan",help="Show Local Dev build plan"); sp.add_argument("--profile",choices=list(PROFILES),default="full")
    sp=sub.add_parser("doctor",help="Run Local Dev doctor"); sp.add_argument("--profile",choices=list(PROFILES),default="full")
    sub.add_parser("start",help="Start Local Dev services")
    sub.add_parser("stop",help="Stop Local Dev services")
    sub.add_parser("status",help="Show Local Dev status")
    sp=sub.add_parser("smoke",help="Run Local Dev compile smoke tests"); sp.add_argument("--profile",choices=list(PROFILES),default="full")
    return p


def main(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    parser=build_parser()
    if not argv:
        try:
            return interactive_main()
        except (EOFError,KeyboardInterrupt):
            print()
            return EXIT_FAIL
    args=parser.parse_args(argv)
    global LOG
    ensure_dirs()
    LOG=Log()
    try:
        if args.command == "docker":
            if args.qemu_provider != "prebuilt": raise BuildError("Docker Strict OSS requires --qemu-provider prebuilt.")
            docker_prepare(); cmd=["build"] + (["--no-cache"] if args.no_cache else []); docker_compose(cmd); docker_compose(["up","-d"]); docker_health(); return EXIT_OK
        if args.command == "local":
            if args.profile == "browser" and args.qemu_provider == "source": LOG.info("Browser profile does not require QEMU; provider selection will be ignored.")
            return bootstrap(args.profile,args.qemu_provider,args.start,args.smoke,args.force)
        if args.command == "docker-build": return (docker_build(args.no_cache) or EXIT_OK)
        if args.command == "docker-rebuild": return (docker_rebuild(args.no_cache) or EXIT_OK)
        if args.command == "docker-start": return (docker_start() or EXIT_OK)
        if args.command == "docker-stop": return (docker_stop() or EXIT_OK)
        if args.command == "docker-restart": return (docker_restart() or EXIT_OK)
        if args.command == "docker-status": return (docker_status() or EXIT_OK)
        if args.command == "docker-logs": return (docker_logs() or EXIT_OK)
        if args.command == "docker-qemu": return (docker_qemu() or EXIT_OK)
        if args.command == "docker-doctor": return docker_doctor()
        if args.command == "docker-clean": return (docker_clean(args.volumes) or EXIT_OK)
        if args.command == "bootstrap": return bootstrap(args.profile,args.qemu_provider,args.start,args.smoke,args.force)
        if args.command == "plan": plan(args.profile); return EXIT_OK
        if args.command == "doctor": return EXIT_OK if doctor(args.profile) else EXIT_FAIL
        if args.command == "start": start(); return EXIT_OK
        if args.command == "stop": stop(); return EXIT_OK
        if args.command == "status": cfg=load_config(); return EXIT_OK if doctor(cfg.get("profile","full")) else EXIT_FAIL
        if args.command == "smoke": return EXIT_OK if smoke(args.profile) else EXIT_FAIL
        parser.print_help(); return EXIT_FAIL
    except BuildError as e:
        LOG.fail(str(e)); return EXIT_FAIL
    except KeyboardInterrupt:
        LOG.warn("Interrupted"); return EXIT_FAIL


if __name__=="__main__": sys.exit(main())
