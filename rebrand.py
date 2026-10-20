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
    patch_locales,
    patch_compose,
    patch_backend,
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
