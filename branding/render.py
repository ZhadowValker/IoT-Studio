import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
svg, png = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
    pg.goto(Path(svg).resolve().as_uri())
    pg.wait_for_timeout(400)
    pg.screenshot(path=png, clip={"x": 0, "y": 0, "width": 1200, "height": 630})
    b.close()
print("rendered", png)
