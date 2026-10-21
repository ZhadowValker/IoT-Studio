#!/usr/bin/env python3
"""IoT-Studio white-label patcher for the Velxio OSS source tree.

build.py runs this against ``our-velxio/upstream`` after cloning and before the
Docker build, so the Velxio source is never committed to this repository and
the rebrand survives re-clones. Every patch is idempotent: running it twice is
safe, and an anchor that no longer exists upstream is reported (not silently
skipped) so a changed Velxio release does not quietly lose part of the rebrand.

What it changes (user-visible surface only):
  * app name in the header, page title, meta/OG tags, PWA manifest, SEO routes
  * Help menu: removes velxio.dev / Discord / pricing links, adds a source-code
    link and an upstream credit (keeps the AGPLv3 §13 source offer visible)
  * disables the GitHub-star popup and the velxio.dev "What's New" news feed
  * strips velxio.dev sitemap / robots / llms.txt marketing content
  * replaces the social-preview image (branding/og-image.png + .svg)
  * recolours the whole UI to #A70CFF / black / white (tokens, literals, favicon)

What it deliberately does NOT change:
  * ``Velxio-GUEST`` - the emulated WiFi SSID baked into QEMU and the tests
  * internal identifiers (component folders, ``velxio-custom-chip`` element,
    ``.vlx`` project extension, storage keys, Docker project/volume names)
  * LICENSE / COMMERCIAL_LICENSE.md - upstream copyright and licence notices
    must stay intact (see NOTICE-IoT-Studio.md, written into the tree)

Configuration (environment variables, all optional):
  IOT_STUDIO_NAME   display name              (default: IoT-Studio)
  IOT_STUDIO_URL    public site URL           (default: http://localhost:3080)
  IOT_STUDIO_SOURCE source-code URL           (default: this repo on GitHub)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BRAND = os.environ.get("IOT_STUDIO_NAME", "IoT-Studio")
SITE_URL = os.environ.get("IOT_STUDIO_URL", "http://localhost:3080").rstrip("/")
SOURCE_URL = os.environ.get(
    "IOT_STUDIO_SOURCE", "https://github.com/ZhadowValker/IoT-Studio"
)
UPSTREAM_URL = "https://github.com/davidmonterocrespo24/velxio"
HERE = Path(__file__).resolve().parent

# Lines in locale files that mention paid / hosted Velxio products. Those
# products do not exist in the white-labelled OSS build, so the wording is
# left untouched rather than inventing "IoT-Studio Desktop" or "IoT-Studio Pro".
LOCALE_SKIP = re.compile(
    r"Desktop|Pro\b|Classroom|velxio\.dev|Velxio-GUEST|\.vlx|Maker|licen[sc]e",
    re.IGNORECASE,
)


class Report:
    def __init__(self) -> None:
        self.applied: list[str] = []
        self.unchanged: list[str] = []
        self.missing: list[str] = []

    def line(self, kind: str, label: str) -> None:
        getattr(self, kind).append(label)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def replace_exact(rep: Report, path: Path, old: str, new: str, label: str) -> None:
    """Replace one exact snippet, idempotently.

    Order matters: the *new* text is checked first because it can contain the
    old anchor (e.g. an inserted line next to it), which would otherwise be
    re-applied on every run. A pure deletion (new == "") is "unchanged" once
    the anchor is gone.
    """
    if not path.is_file():
        rep.line("missing", f"{label} (file not found: {path.name})")
        return
    text = _read(path)
    if new and new in text:
        rep.line("unchanged", label)
    elif old in text:
        _write(path, text.replace(old, new, 1))
        rep.line("applied", label)
    elif not new:
        rep.line("unchanged", label)
    else:
        rep.line("missing", f"{label} (anchor not found in {path.name})")


def replace_regex(
    rep: Report, path: Path, pattern: str, repl, label: str, flags: int = 0
) -> None:
    if not path.is_file():
        rep.line("missing", f"{label} (file not found: {path.name})")
        return
    text = _read(path)
    new_text, n = re.subn(pattern, repl, text, flags=flags)
    if n and new_text != text:
        _write(path, new_text)
        rep.line("applied", label)
    else:
        rep.line("unchanged", label)


# --------------------------------------------------------------------------- #
# Individual patches
# --------------------------------------------------------------------------- #

def patch_index_html(tree: Path, rep: Report) -> None:
    path = tree / "frontend" / "index.html"
    if not path.is_file():
        rep.line("missing", "index.html (file not found)")
        return
    text = _read(path)
    before = text

    # Drop social handles that belong to the upstream project.
    text = re.sub(r'\s*<meta name="twitter:(site|creator)"[^>]*>', "", text)
    # Author meta credits the upstream author; attribution lives in NOTICE and
    # the Help menu instead of a meta tag that would imply this is their site.
    text = re.sub(
        r'(<meta name="author" content=")[^"]*(")', rf"\g<1>{BRAND}\g<2>", text
    )
    # Public URLs -> configured site URL (og:url, og:image, canonical hints).
    text = text.replace("https://velxio.dev", SITE_URL)
    # Keyword stuffing token and brand name.
    text = text.replace(", velxio\"", f", {BRAND.lower()}\"")
    # "Velxio Desktop" is a separate paid product that does not exist here.
    text = re.sub(r"Velxio(?! Desktop)", BRAND, text)
    text = text.replace(f"{BRAND} Desktop", "Velxio Desktop")

    if text != before:
        _write(path, text)
        rep.line("applied", "index.html title / meta / Open Graph")
    else:
        rep.line("unchanged", "index.html title / meta / Open Graph")


def patch_header(tree: Path, rep: Report) -> None:
    replace_exact(
        rep,
        tree / "frontend/src/components/layout/AppHeader.tsx",
        '<span className="header-title">Velxio</span>',
        f'<span className="header-title">{BRAND}</span>',
        "header brand title",
    )


def patch_help_menu(tree: Path, rep: Report) -> None:
    path = tree / "frontend/src/components/editor/EditorMenuBar.tsx"

    replace_exact(
        rep,
        path,
        "const GITHUB_URL = 'https://github.com/davidmonterocrespo24/velxio';",
        f"const GITHUB_URL = '{SOURCE_URL}';",
        "menu: source URL constant",
    )
    # DISCORD_URL becomes the upstream credit link (keeps the symbol used, so
    # tsconfig's noUnusedLocals stays satisfied).
    replace_exact(
        rep,
        path,
        "const DISCORD_URL = 'https://discord.gg/3mARjJrh4E';",
        f"const UPSTREAM_URL = '{UPSTREAM_URL}';",
        "menu: upstream credit constant",
    )
    # SITE only fed the removed velxio.dev links; drop it (noUnusedLocals).
    replace_exact(
        rep,
        path,
        "const SITE = import.meta.env.VITE_PRO_BUILD ? '' : 'https://velxio.dev';\n",
        "",
        "menu: remove velxio.dev SITE constant",
    )
    replace_exact(
        rep,
        path,
        """    { kind: 'link', href: `${SITE}/docs`, label: t('header.nav.documentation', 'Documentation') },
    { kind: 'link', href: '/examples', label: t('header.nav.examples', 'Examples') },
    { kind: 'link', href: `${SITE}/pricing`, label: t('header.nav.pricing', 'Pricing') },
    { kind: 'separator' },
    { kind: 'link', href: SITE || '/', label: t('editor.menu.home', 'Velxio Home') },
    { kind: 'link', href: `${SITE}/blog/`, label: t('header.nav.blog', 'Blog') },
    { kind: 'link', href: `${SITE}/about`, label: t('editor.menu.about', 'About Velxio') },
    { kind: 'separator' },
    { kind: 'link', href: DISCORD_URL, label: t('editor.menu.discord', 'Discord Community') },
    { kind: 'link', href: GITHUB_URL, label: t('editor.menu.github', 'GitHub Repository') },
""",
        """    { kind: 'link', href: '/examples', label: t('header.nav.examples', 'Examples') },
    { kind: 'separator' },
    { kind: 'link', href: GITHUB_URL, label: 'Source code (AGPLv3)' },
    { kind: 'link', href: UPSTREAM_URL, label: 'Built on Velxio (open source)' },
""",
        "menu: Help links (drop velxio.dev / Discord / pricing, add source + credit)",
    )


def patch_popups(tree: Path, rep: Report) -> None:
    path = tree / "frontend/src/pages/EditorPage.tsx"
    # `false &&` keeps both imports referenced, so noUnusedLocals still passes.
    replace_exact(
        rep, path,
        "{showStarBanner && (",
        "{false && showStarBanner && (",
        "disable GitHub-star popup",
    )
    replace_exact(
        rep, path,
        "      <NewsAnnouncer />",
        "      {false && <NewsAnnouncer />}",
        "disable velxio.dev news popup (UI)",
    )


def patch_manifest(tree: Path, rep: Report) -> None:
    path = tree / "frontend/public/manifest.webmanifest"
    if not path.is_file():
        rep.line("missing", "manifest.webmanifest (file not found)")
        return
    data = json.loads(_read(path))
    wanted = {
        "name": f"{BRAND} — Circuit & Microcontroller Simulator",
        "short_name": BRAND,
        "description": (
            "Browser-based circuit and microcontroller simulator. ESP32, RP2040, "
            "Arduino, ATtiny85, SPICE analog simulation. Open source (AGPLv3)."
        ),
    }
    changed = any(data.get(k) != v for k, v in wanted.items())
    data.update(wanted)
    for shot in data.get("screenshots", []):
        if "Velxio" in shot.get("label", ""):
            shot["label"] = shot["label"].replace("Velxio", BRAND)
            changed = True
    if changed:
        _write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        rep.line("applied", "PWA manifest")
    else:
        rep.line("unchanged", "PWA manifest")


def patch_seo_files(tree: Path, rep: Report) -> None:
    pub = tree / "frontend" / "public"

    robots = pub / "robots.txt"
    replace_regex(
        rep, robots, r"^Sitemap:.*velxio\.dev.*\n?", "", "robots.txt: drop velxio.dev sitemaps",
        flags=re.MULTILINE,
    )

    sitemap = pub / "sitemap.xml"
    if sitemap.is_file():
        text = _read(sitemap)
        if "velxio.dev" in text:
            _write(
                sitemap,
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"  <url><loc>{SITE_URL}/editor/</loc></url>\n"
                f"  <url><loc>{SITE_URL}/examples/</loc></url>\n"
                "</urlset>\n",
            )
            rep.line("applied", "sitemap.xml (velxio.dev URLs removed)")
        else:
            rep.line("unchanged", "sitemap.xml")
    else:
        rep.line("missing", "sitemap.xml (file not found)")

    llms = pub / "llms.txt"
    if llms.is_file():
        body = (
            f"# {BRAND} — Circuit & Microcontroller Simulator\n\n"
            f"> {BRAND} is a browser-based simulator for microcontrollers "
            "(Arduino, ESP32, RP2040, RISC-V, ATtiny85) with SPICE analog "
            "co-simulation. Self-hosted, open source (AGPLv3).\n\n"
            f"- Source: {SOURCE_URL}\n"
            f"- Built on Velxio: {UPSTREAM_URL}\n"
        )
        if _read(llms) == body:
            rep.line("unchanged", "llms.txt")
        else:
            _write(llms, body)
            rep.line("applied", "llms.txt")
    else:
        rep.line("missing", "llms.txt (file not found)")


def patch_seo_routes(tree: Path, rep: Report) -> None:
    path = tree / "frontend/src/seoRoutes.ts"
    if not path.is_file():
        rep.line("missing", "seoRoutes.ts (file not found)")
        return
    text = _read(path)
    new = text.replace("https://velxio.dev", SITE_URL).replace("Velxio", BRAND)
    if new != text:
        _write(path, new)
        rep.line("applied", "seoRoutes.ts titles / descriptions / domain")
    else:
        rep.line("unchanged", "seoRoutes.ts titles / descriptions / domain")


def patch_canonical_urls(tree: Path, rep: Report) -> None:
    """Point canonical / sitemap / structured-data URLs at this site.

    Left on velxio.dev these would declare velxio.dev as the canonical home of
    every page, which tells search engines this site is a duplicate of it.
    """
    fe = tree / "frontend"
    files = (
        "src/utils/useSEO.ts",
        "src/pages/EditorPage.tsx",
        "src/pages/ProjectByIdPage.tsx",
        "src/pages/ExampleEditorPage.tsx",
        "src/pages/ExampleDetailPage.tsx",
        "src/entry-server.tsx",
        "scripts/generate-sitemap.mjs",
        "scripts/generate-sitemap.ts",
        "scripts/prerender-seo.mjs",
    )
    changed, missing = 0, []
    for name in files:
        path = fe / name
        if not path.is_file():
            missing.append(name)
            continue
        text = _read(path)
        if "https://velxio.dev" in text:
            _write(path, text.replace("https://velxio.dev", SITE_URL))
            changed += 1
    for name in missing:
        rep.line("missing", f"canonical URLs (file not found: {name})")
    rep.line("applied" if changed else "unchanged", f"canonical/sitemap URLs ({changed} files)")

    # Breadcrumb on the example detail page.
    replace_regex(
        rep,
        fe / "src/pages/ExampleDetailPage.tsx",
        r'(<Link to="/"[^>]*>\s*)Velxio(\s*</Link>)',
        rf"\g<1>{BRAND}\g<2>",
        "example page breadcrumb",
    )

    # README that ships inside exported project zips.
    wokwi = fe / "src/utils/wokwiZip.ts"
    if wokwi.is_file():
        text = _read(wokwi)
        new = text.replace("Exported from Velxio", f"Exported from {BRAND}").replace(
            "Simulate this project on https://velxio.dev", f"Simulate this project on {SITE_URL}"
        )
        if new != text:
            _write(wokwi, new)
            rep.line("applied", "exported-zip README text")
        else:
            rep.line("unchanged", "exported-zip README text")


def patch_page_titles(tree: Path, rep: Report) -> None:
    """Page titles, JSON-LD and SSR text for pages the OSS build serves."""
    fe = tree / "frontend"
    files = (
        "src/pages/EditorPage.tsx",
        "src/pages/ProjectByIdPage.tsx",
        "src/pages/ExampleEditorPage.tsx",
        "src/pages/ExampleDetailPage.tsx",
        "src/entry-server.tsx",
        "src/components/examples/CommunityProjectsGrid.tsx",
    )
    # Whole word only; never the emulated WiFi SSID or the paid Desktop product.
    pattern = re.compile(r"\bVelxio\b(?!-GUEST| Desktop)")
    changed = 0
    for name in files:
        path = fe / name
        if not path.is_file():
            rep.line("missing", f"page titles (file not found: {name})")
            continue
        text = _read(path)
        new = pattern.sub(BRAND, text)
        if new != text:
            _write(path, new)
            changed += 1
    rep.line("applied" if changed else "unchanged", f"page titles / JSON-LD / SSR text ({changed} files)")


def patch_og_image(tree: Path, rep: Report) -> None:
    """Replace the Velxio social-preview image with branding/og-image.*.

    The shipped image has the name "IoT-Studio" drawn into it, so it is only
    copied when IOT_STUDIO_NAME is the default. For a custom name, regenerate
    it with branding/make_og.py + branding/render.py and drop it in branding/.
    """
    src = HERE / "branding"
    public = tree / "frontend" / "public"
    if BRAND != "IoT-Studio" and not os.environ.get("IOT_STUDIO_FORCE_OG"):
        rep.line("unchanged", "og-image (custom name: regenerate branding/og-image.*)")
        return
    changed, missing = 0, []
    for name in ("og-image.png", "og-image.svg"):
        source, target = src / name, public / name
        if not source.is_file():
            missing.append(f"og-image (branding/{name} not found)")
            continue
        data = source.read_bytes()
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
            changed += 1
    for item in missing:
        rep.line("missing", item)
    rep.line("applied" if changed else "unchanged", f"og-image.png/.svg ({changed} files)")


# --------------------------------------------------------------------------- #
# Theme: #A70CFF + black + white
# --------------------------------------------------------------------------- #

ACCENT = "#A70CFF"

# Primitive scale. Greys are neutral (the stock ones carry a blue cast); the
# old --blue-* accent scale is repointed at a purple scale built on ACCENT.
# 600 is the brand colour (white text on it is 5.1:1), 400 is the lighter
# tint for text on dark, 700 the darker one for text/hover on white.
THEME_PRIMITIVES = {
    "gray-100": "#f4f4f4", "gray-200": "#e6e6e6", "gray-300": "#cfcfcf",
    "gray-400": "#a8a8a8", "gray-500": "#858585", "gray-600": "#666666",
    "gray-700": "#3d3d3d", "gray-800": "#252525", "gray-850": "#171717",
    "gray-900": "#0e0e0e", "gray-950": "#050505",
    "blue-400": "#D07BFF", "blue-500": "#B82EFF", "blue-600": ACCENT,
    "blue-700": "#8300CC",
}

THEME_DARK = {
    "wb-0": "#000000", "wb-1": "#0a0a0a", "wb-2": "#0d0d0d", "wb-3": "#141414",
    "wb-4": "#1a1a1a", "wb-5": "#1f1f1f", "wb-6": "#2a2a2a", "wb-7": "#383838",
    "wb-13": "#ffffff",
    "color-bg-header": "rgba(5, 5, 5, 0.88)",
    "color-canvas-label-bg": "rgba(10, 10, 10, 0.85)",
    "color-wire-outline": "#0a0a0a",
    "color-terminal-bg": "#000000",
    "color-terminal-fg": "#ffffff",
}

THEME_LIGHT = {
    "wb-0": "#fcfcfc", "wb-1": "#ececec", "wb-3": "#f2f2f2", "wb-4": "#e6e6e6",
    "wb-6": "#d9d9d9", "wb-7": "#c4c4c4", "wb-8": "#a8a8a8", "wb-9": "#8a8a8a",
    "wb-10": "#6b6b6b", "wb-11": "#4d4d4d", "wb-12": "#1f1f1f", "wb-13": "#000000",
    "color-bg-canvas": "#f2f2f2", "color-bg-surface-2": "#f7f7f7",
    "color-bg-overlay": "rgba(0, 0, 0, 0.40)",
    "color-bg-header": "rgba(255, 255, 255, 0.88)",
    "color-canvas-grid": "rgba(0, 0, 0, 0.07)",
    "color-canvas-shadow": "rgba(0, 0, 0, 0.16)",
    "color-symbol-ink": "#1a1a1a", "color-symbol-lead": "#4d4d4d",
    "color-symbol-label": "#262626", "color-symbol-body": "#8a8a8a",
    "color-wire-marker": "#1a1a1a",
    "color-terminal-fg": "#1a1a1a",
}

GRADIENT_DARK = (
    "\n  /* IoT-Studio brand gradients */\n"
    f"  --brand: {ACCENT};\n"
    f"  --gradient-brand-text: linear-gradient(90deg, #ffffff 0%, {ACCENT} 100%);\n"
    f"  --gradient-brand-line: linear-gradient(90deg, rgba(167, 12, 255, 0) 0%, {ACCENT} 35%, "
    "rgba(255, 255, 255, 0.6) 70%, rgba(255, 255, 255, 0) 100%);"
)
GRADIENT_LIGHT = (
    "\n  /* IoT-Studio brand gradients */\n"
    f"  --brand: {ACCENT};\n"
    f"  --gradient-brand-text: linear-gradient(90deg, #000000 0%, {ACCENT} 100%);\n"
    f"  --gradient-brand-line: linear-gradient(90deg, rgba(167, 12, 255, 0) 0%, {ACCENT} 35%, "
    "rgba(0, 0, 0, 0.5) 70%, rgba(0, 0, 0, 0) 100%);"
)

# Hard-coded brand blues in components -> the new scale. Content colours
# (wire colours, board/part colours, probe cyan, syntax colours, #4fc3f7
# board-type tags, success/error/warning) are deliberately not touched.
THEME_LITERALS = {
    "#007acc": ACCENT, "#0071e3": ACCENT, "#0e639c": ACCENT,
    "#58a6ff": "#D07BFF", "#4ea8ff": "#D07BFF",
    "#0a84ff": "#B82EFF", "#0058b3": "#8300CC",
}
THEME_RGBA = (
    (re.compile(r"rgba\(\s*0,\s*113,\s*227,"), "rgba(167, 12, 255,"),
    (re.compile(r"rgba\(\s*0,\s*122,\s*204,"), "rgba(167, 12, 255,"),
    (re.compile(r"rgba\(\s*88,\s*166,\s*255,"), "rgba(167, 12, 255,"),
)
THEME_SKIP_DIRS = {"velxio-components", "__tests__", "i18n", "data", "node_modules", "dist"}

THEME_CSS = f"""/* IoT-Studio theme: {ACCENT} / black / white. Generated by rebrand.py.
 * Colour tokens themselves live in tokens/colors.css; this file only holds the
 * few brand accents that tokens alone cannot express (gradients, selection). */

:root {{
  accent-color: var(--brand, {ACCENT});
}}

::selection {{
  background: rgba(167, 12, 255, 0.45);
  color: #ffffff;
}}

/* Header wordmark: white -> purple (black -> purple in the light theme). */
.header-title {{
  background: var(--gradient-brand-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
  font-weight: 700;
  letter-spacing: -0.3px;
}}

/* Hairline gradient under the app header. */
.app-header {{
  border-image: var(--gradient-brand-line) 1;
}}
"""


def _set_tokens(chunk: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    missing = []
    for name, value in mapping.items():
        pattern = re.compile(rf"(--{re.escape(name)}:\s*)([^;]+)(;)")
        if pattern.search(chunk):
            chunk = pattern.sub(lambda m: f"{m.group(1)}{value}{m.group(3)}", chunk, count=1)
        else:
            missing.append(name)
    return chunk, missing


def patch_theme_tokens(tree: Path, rep: Report) -> None:
    path = tree / "frontend/src/tokens/colors.css"
    if not path.is_file():
        rep.line("missing", "theme tokens (colors.css not found)")
        return
    text = _read(path)

    themed = text.find("/* Everything below is THEMED")
    light = text.find(":root[data-theme='light'],")
    if themed < 0 or light < 0 or not themed < light:
        rep.line("missing", "theme tokens (colors.css layout changed upstream)")
        return

    prim, dark, lite = text[:themed], text[themed:light], text[light:]
    gone: list[str] = []
    prim, m = _set_tokens(prim, THEME_PRIMITIVES); gone += m
    dark, m = _set_tokens(dark, THEME_DARK); gone += m
    lite, m = _set_tokens(lite, THEME_LIGHT); gone += m

    for pattern, repl in THEME_RGBA:
        prim = pattern.sub(repl, prim)
        dark = pattern.sub(repl, dark)
        lite = pattern.sub(repl, lite)

    anchor = re.compile(r"(--color-accent-border:[^;]+;)")
    if "--gradient-brand-text" not in dark:
        dark, n = anchor.subn(lambda m: m.group(1) + GRADIENT_DARK, dark, count=1)
        if not n:
            gone.append("gradient tokens (dark)")
    if "--gradient-brand-text" not in lite:
        lite, n = anchor.subn(lambda m: m.group(1) + GRADIENT_LIGHT, lite, count=1)
        if not n:
            gone.append("gradient tokens (light)")

    new = prim + dark + lite
    if new != text:
        _write(path, new)
        rep.line("applied", "theme: colour tokens (dark + light)")
    else:
        rep.line("unchanged", "theme: colour tokens (dark + light)")
    for name in gone:
        rep.line("missing", f"theme token not found upstream: {name}")


def patch_theme_literals(tree: Path, rep: Report) -> None:
    fe = tree / "frontend"
    files = [fe / "index.html"]
    for ext in ("*.tsx", "*.ts", "*.css"):
        files += [
            p for p in (fe / "src").rglob(ext)
            if not (THEME_SKIP_DIRS & set(p.parts)) and ".test." not in p.name
        ]
    hex_re = re.compile("|".join(re.escape(k) for k in THEME_LITERALS), re.IGNORECASE)
    changed = 0
    for path in files:
        if not path.is_file():
            continue
        text = _read(path)
        new = hex_re.sub(lambda m: THEME_LITERALS[m.group(0).lower()], text)
        for pattern, repl in THEME_RGBA:
            new = pattern.sub(repl, new)
        if new != text:
            _write(path, new)
            changed += 1
    rep.line("applied" if changed else "unchanged", f"theme: hard-coded brand blues ({changed} files)")


def patch_theme_extras(tree: Path, rep: Report) -> None:
    fe = tree / "frontend"

    # 1. Brand-accent stylesheet + import.
    css = fe / "src/theme-iot-studio.css"
    if not css.is_file() or _read(css) != THEME_CSS:
        _write(css, THEME_CSS)
        rep.line("applied", "theme: brand stylesheet (gradients, selection)")
    else:
        rep.line("unchanged", "theme: brand stylesheet (gradients, selection)")
    replace_exact(
        rep, fe / "src/index.css",
        "@import './tokens/index.css';\n",
        "@import './tokens/index.css';\n@import './theme-iot-studio.css';\n",
        "theme: import brand stylesheet",
    )

    # 2. Code-editor selection colour (was a dark blue).
    mt = fe / "src/components/editor/monacoThemes.ts"
    replace_exact(rep, mt, "selection: '#264f78'", "selection: '#4a1673'", "theme: editor selection (dark)")
    replace_exact(rep, mt, "selection: '#add6ff'", "selection: '#e8c8ff'", "theme: editor selection (light)")

    # 3. Pre-paint colours in index.html must match the new canvas, or the page
    #    flashes the old grey before the stylesheet loads.
    index = fe / "index.html"
    if index.is_file():
        text = _read(index)
        new = (
            text.replace("#0a0a0c", "#050505")
            .replace("#f5f5f7", "#f2f2f2")
            .replace("#0d1117", "#000000")
            .replace("#161b22", "#12001f")
        )
        if new != text:
            _write(index, new)
            rep.line("applied", "theme: index.html pre-paint colours")
        else:
            rep.line("unchanged", "theme: index.html pre-paint colours")

    # 4. PWA colours.
    manifest = fe / "public/manifest.webmanifest"
    if manifest.is_file():
        data = json.loads(_read(manifest))
        want = {"theme_color": ACCENT, "background_color": "#000000"}
        if any(data.get(k) != v for k, v in want.items()):
            data.update(want)
            _write(manifest, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            rep.line("applied", "theme: manifest colours")
        else:
            rep.line("unchanged", "theme: manifest colours")

    # 5. Favicon set.
    src = HERE / "branding"
    names = (
        "favicon.svg", "favicon.ico", "favicon-16x16.png", "favicon-32x32.png",
        "favicon-48x48.png", "apple-touch-icon.png", "android-chrome-192.png",
        "android-chrome-512.png",
    )
    changed = 0
    for name in names:
        source, target = src / name, fe / "public" / name
        if not source.is_file():
            rep.line("missing", f"favicon (branding/{name} not found)")
            continue
        data = source.read_bytes()
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
            changed += 1
    rep.line("applied" if changed else "unchanged", f"theme: favicon set ({changed} files)")


def patch_theme(tree: Path, rep: Report) -> None:
    patch_theme_tokens(tree, rep)
    patch_theme_literals(tree, rep)
    patch_theme_extras(tree, rep)


def patch_locales(tree: Path, rep: Report) -> None:
    root = tree / "frontend/src/i18n/locales"
    if not root.is_dir():
        rep.line("missing", "i18n locales (folder not found)")
        return
    touched = 0
    for path in sorted(root.glob("*/common*.json")):
        lines = _read(path).splitlines(keepends=True)
        out, changed = [], False
        for line in lines:
            if "Velxio" in line and not LOCALE_SKIP.search(line):
                line = line.replace("Velxio", BRAND)
                changed = True
            out.append(line)
        if changed:
            _write(path, "".join(out))
            touched += 1
    if touched:
        rep.line("applied", f"i18n strings ({touched} locale files)")
    else:
        rep.line("unchanged", "i18n strings")


def patch_compose(tree: Path, rep: Report) -> None:
    path = tree / "docker-compose.oss.yml"
    replace_exact(
        rep,
        path,
        '      VITE_PRO_BUILD: ""\n',
        '      VITE_PRO_BUILD: ""\n      VELXIO_NEWS: "off"\n',
        "compose: VELXIO_NEWS=off (no velxio.dev feed)",
    )


def patch_backend(tree: Path, rep: Report) -> None:
    replace_exact(
        rep,
        tree / "backend/app/main.py",
        'title="Arduino Emulator API",',
        f'title="{BRAND} API",',
        "backend API title",
    )


def patch_build_fixes(tree: Path, rep: Report) -> None:
    """Fixes for upstream build breakage that is independent of branding.

    Velxio's frontend has no committed lockfile, so ``npm install`` resolves
    the newest matching dependency versions on every build. With the current
    tree, npm 10 crashes in its resolver ("Cannot read properties of null
    (reading 'edgesOut')") unless peer-dependency resolution is relaxed.
    """
    replace_exact(
        rep,
        tree / "Dockerfile.oss",
        " && npm install --include=optional \\\n",
        " && npm install --include=optional --legacy-peer-deps \\\n",
        "build fix: npm install --legacy-peer-deps (Dockerfile.oss)",
    )


def patch_wifi_status(tree: Path, rep: Report) -> None:
    """Let the WiFi badge / Serial Monitor gateway link go green for sketches.

    Upstream derives the "got an IP" state only from ESP-IDF info logs
    (``sta ip: ...``). The Arduino build here logs at warning level, so those
    lines never reach the serial stream and the badge stays grey forever --
    which also hides the Serial Monitor's "Open IoT Gateway" link, even though
    the sketch printed its address and the proxy would work. Treat a
    192.168.4.x address printed by the sketch as got_ip (.1/.2/.3 are the
    soft-AP / gateway / DNS addresses, never the station's lease).
    """
    path = tree / "backend" / "app" / "services" / "wifi_status_parser.py"
    replace_exact(
        rep,
        path,
        "# ── BLE patterns ──",
        "# IoT-Studio: station address printed by the sketch itself (not .1-.3).\n"
        "_RE_SKETCH_STA_IP = re.compile(\n"
        "    r'\\b(192\\.168\\.4\\.(?!(?:1|2|3)(?!\\d))\\d{1,3})(?!\\d)'\n"
        ")\n\n"
        "# ── BLE patterns ──",
        "wifi status: sketch-printed IP regex",
    )
    replace_exact(
        rep,
        path,
        "    if _RE_WIFI_CONNECTED.search(line):\n"
        "        m = _RE_WIFI_CONNECTED.search(line)\n",
        "    m = _RE_SKETCH_STA_IP.search(line)\n"
        "    if m:\n"
        "        return WifiEvent(status='got_ip', ip=m.group(1))\n\n"
        "    if _RE_WIFI_CONNECTED.search(line):\n"
        "        m = _RE_WIFI_CONNECTED.search(line)\n",
        "wifi status: treat sketch-printed IP as got_ip",
    )


def patch_wifi_line_buffer(tree: Path, rep: Report) -> None:
    """Parse WiFi status from whole serial lines, not flush-sized chunks.

    The backend's UART buffer flushes on every '.', so an address such as
    ``192.168.4.15`` reaches the status parser in four pieces and can never
    match (ESP-IDF's own ``sta ip: 192.168.4.2`` lines suffer the same).
    Accumulate the text and hand the parser complete lines only.
    """
    path = tree / "backend" / "app" / "services" / "esp32_lib_manager.py"
    pad = " " * 32
    replace_exact(
        rep,
        path,
        pad + "wifi_evts, ble_evts = parse_serial_text(text)\n",
        pad + "# IoT-Studio: parse complete lines (the buffer flushes on '.').\n"
        + pad + "_wt = (getattr(inst, '_wifi_tail', '') + text)[-4096:]\n"
        + pad + "_wt_done = ''\n"
        + pad + "if '\\n' in _wt or '\\r' in _wt:\n"
        + pad + "    _cut = max(_wt.rfind('\\n'), _wt.rfind('\\r')) + 1\n"
        + pad + "    _wt_done, _wt = _wt[:_cut], _wt[_cut:]\n"
        + pad + "setattr(inst, '_wifi_tail', _wt)\n"
        + pad + "wifi_evts, ble_evts = parse_serial_text(_wt_done)\n",
        "wifi status: parse whole serial lines",
    )


def patch_serial_noise(tree: Path, rep: Report) -> None:
    """Hide the QEMU WiFi PHY clock warning from the serial monitor.

    The emulated ESP32 has no real radio clock gating, so ESP-IDF prints
    ``W (n) periph_ctrl: phy module clock bits 0x0, required 0x8f8f`` about
    once a second while WiFi is on. It is harmless and buries the sketch's own
    output, so whole lines matching it are dropped before they are forwarded.
    """
    path = tree / "backend" / "app" / "services" / "esp32_lib_manager.py"
    replace_exact(
        rep,
        path,
        "class _UartBuffer:\n",
        "_IOTS_NOISE = ('periph_ctrl: phy module clock bits',)\n"
        "\n\n"
        "def _iots_filter(inst, text: str) -> str:\n"
        "    \"\"\"IoT-Studio: drop known-harmless emulator log lines, keep everything else.\n"
        "    A partial line is held back only while it looks like an ESP-IDF 'W (' log\n"
        "    line, so prompts without a newline still show immediately.\"\"\"\n"
        "    pend = getattr(inst, '_noise_tail', '') + text\n"
        "    cut = max(pend.rfind('\\n'), pend.rfind('\\r')) + 1\n"
        "    done, rest = pend[:cut], pend[cut:]\n"
        "    out = ''.join(\n"
        "        ln for ln in done.splitlines(True)\n"
        "        if not any(n in ln for n in _IOTS_NOISE)\n"
        "    )\n"
        "    if rest[:3] == 'W (' or (rest and 'W (' [:len(rest)] == rest):\n"
        "        setattr(inst, '_noise_tail', rest[-512:])\n"
        "    else:\n"
        "        setattr(inst, '_noise_tail', '')\n"
        "        out += rest\n"
        "    return out\n"
        "\n\n"
        "class _UartBuffer:\n",
        "serial: noise filter helper",
    )
    pad = " " * 28
    replace_exact(
        rep,
        path,
        pad + "self._dispatch(inst, 'serial_output', {\n"
        + pad + "    'data': text, 'uart': uart_id,\n"
        + pad + "})\n",
        pad + "_shown = _iots_filter(inst, text) if uart_id == 0 else text\n"
        + pad + "if _shown:\n"
        + pad + "    self._dispatch(inst, 'serial_output', {\n"
        + pad + "        'data': _shown, 'uart': uart_id,\n"
        + pad + "    })\n",
        "serial: drop PHY clock warning lines",
    )


def write_notice(tree: Path, rep: Report) -> None:
    path = tree / "NOTICE-IoT-Studio.md"
    body = (
        f"# {BRAND} — attribution notice\n\n"
        f"{BRAND} is a rebranded build of **Velxio**, an open-source project by "
        "David Montero Crespo, licensed under the GNU AGPL v3 "
        f"({UPSTREAM_URL}).\n\n"
        "The original LICENSE and COMMERCIAL_LICENSE.md files in this tree are "
        "unchanged and still apply. Modified, network-accessible deployments "
        "must offer their corresponding source under the same licence; the "
        f"modifications made by this build live at {SOURCE_URL} "
        "(see `rebrand.py`).\n\n"
        "Emulation components credited by upstream (Wokwi avr8js / rp2040js, "
        "lcgamboa QEMU fork, ngspice) keep their own licences.\n"
    )
    if path.is_file() and _read(path) == body:
        rep.line("unchanged", "NOTICE-IoT-Studio.md")
    else:
        _write(path, body)
        rep.line("applied", "NOTICE-IoT-Studio.md")


PATCHES = (
    patch_index_html,
    patch_header,
    patch_help_menu,
    patch_popups,
    patch_manifest,
    patch_seo_files,
    patch_seo_routes,
    patch_canonical_urls,
    patch_page_titles,
    patch_og_image,
    patch_theme,
    patch_locales,
    patch_compose,
    patch_backend,
    patch_build_fixes,
    patch_wifi_status,
    patch_wifi_line_buffer,
    patch_serial_noise,
    write_notice,
)


def apply(tree: Path) -> Report:
    """Apply every patch to *tree* and return a Report."""
    rep = Report()
    for patch in PATCHES:
        patch(tree, rep)
    return rep


def main(argv: list[str]) -> int:
    tree = Path(argv[1]) if len(argv) > 1 else Path("our-velxio") / "upstream"
    if not (tree / "frontend" / "index.html").is_file():
        print(f"error: {tree} does not look like a Velxio checkout", file=sys.stderr)
        return 2
    rep = apply(tree)
    for label in rep.applied:
        print(f"  applied    {label}")
    for label in rep.unchanged:
        print(f"  unchanged  {label}")
    for label in rep.missing:
        print(f"  MISSING    {label}")
    return 1 if rep.missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
