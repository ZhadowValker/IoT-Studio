#!/usr/bin/env python3
"""IoT-Studio agent overlay: copies ``overlay/`` into the Velxio tree and
applies the few anchored hook patches that mount it.

Run by ``build.py`` after ``rebrand``. Idempotent. Set ``IOT_STUDIO_AGENT=0``
to build without the agent. Reuses the helpers from ``rebrand.py``.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import rebrand
from rebrand import Report, replace_exact

HERE = Path(__file__).resolve().parent
OVERLAY = HERE / "overlay"

# Overlay sub-trees that are source (tests stay in the repo, not the image).
SKIP_DIRS = {"__pycache__", "tests_agent", ".pytest_cache"}


def copy_overlay(tree: Path, rep: Report) -> None:
    if not OVERLAY.is_dir():
        rep.line("missing", "overlay/ directory not found")
        return
    for src in sorted(OVERLAY.rglob("*")):
        rel = src.relative_to(OVERLAY)
        if src.is_dir() or SKIP_DIRS & set(rel.parts) or src.suffix == ".pyc":
            continue
        dst = tree / rel
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            rep.line("unchanged", f"overlay: {rel}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        rep.line("applied", f"overlay: {rel}")


def patch_hooks(tree: Path, rep: Report) -> None:
    replace_exact(
        rep,
        tree / "backend" / "app" / "main.py",
        "# Include routers\n",
        "# Include routers\n"
        "from app.agent.router import router as _iot_agent_router  # IoT-Studio agent\n"
        'app.include_router(_iot_agent_router, prefix="/api/agent", tags=["agent"])\n',
        "agent: mount /api/agent router (main.py)",
    )
    page = tree / "frontend" / "src" / "pages" / "EditorPage.tsx"
    replace_exact(
        rep,
        page,
        "import '../App.css';\n",
        "import { AgentPanel } from '../agent/AgentPanel';\nimport '../App.css';\n",
        "agent: import AgentPanel (EditorPage.tsx)",
    )
    replace_exact(
        rep,
        page,
        "          )}\n        </div>\n      </div>\n\n      {",
        "          )}\n        </div>\n"
        "        {/* IoT-Studio AI agent: docked as a third column, not over the canvas */}\n"
        "        <AgentPanel />\n"
        "      </div>\n\n      {",
        "agent: dock AgentPanel beside the simulator (EditorPage.tsx)",
    )
    canvas = tree / "frontend" / "src" / "components" / "simulator" / "SimulatorCanvas.tsx"
    replace_exact(
        rep,
        canvas,
        "import { ComponentPickerModal } from '../ComponentPickerModal';\n",
        "import { ComponentPickerModal } from '../ComponentPickerModal';\n"
        "import { AgentLauncher } from '../../agent/AgentLauncher';\n",
        "agent: import AgentLauncher (SimulatorCanvas.tsx)",
    )
    replace_exact(
        rep,
        canvas,
        "                  {t('editor.canvas.add')}\n                </button>\n",
        "                  {t('editor.canvas.add')}\n                </button>\n"
        "\n                {/* IoT-Studio AI agent launcher, next to Add */}\n"
        "                <AgentLauncher />\n",
        "agent: launcher next to Add (SimulatorCanvas.tsx)",
    )
    replace_exact(
        rep,
        tree / "docker" / "nginx.conf",
        "    # Proxy /api/* requests to the FastAPI backend.\n",
        "    # IoT-Studio agent: streamed LLM responses must not be buffered.\n"
        "    location /api/agent/ {\n"
        "        proxy_pass http://127.0.0.1:8001/api/agent/;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_buffering off;\n"
        "        proxy_cache off;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_read_timeout 600s;\n"
        "    }\n\n"
        "    # Proxy /api/* requests to the FastAPI backend.\n",
        "agent: unbuffered /api/agent/ proxy (nginx.conf)",
    )


def apply(tree: Path) -> Report:
    rep = Report()
    copy_overlay(tree, rep)
    patch_hooks(tree, rep)
    return rep


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "our-velxio" / "upstream"
    report = apply(target)
    print(f"applied={len(report.applied)} unchanged={len(report.unchanged)} missing={len(report.missing)}")
    for item in report.missing:
        print("  missing:", item)
    sys.exit(1 if report.missing else 0)
