"""Generate the IoT-Studio OG image (SVG) in the #A70CFF / black / white palette."""
import sys

P = "#A70CFF"
W, H = 1200, 630

# ---- chip geometry (right half) ----
cx, cy, size = 905, 315, 210
x0, y0 = cx - size / 2, cy - size / 2
x1, y1 = cx + size / 2, cy + size / 2
n, pitch, plen = 6, 30, 26
offs = [(i - (n - 1) / 2) * pitch for i in range(n)]

pins = []
for o in offs:
    pins.append((cx + o, y0, cx + o, y0 - plen))   # top
    pins.append((cx + o, y1, cx + o, y1 + plen))   # bottom
    pins.append((x0, cy + o, x0 - plen, cy + o))   # left
    pins.append((x1, cy + o, x1 + plen, cy + o))   # right
pin_svg = "\n".join(
    f'<line x1="{a:.0f}" y1="{b:.0f}" x2="{c:.0f}" y2="{d:.0f}"/>' for a, b, c, d in pins
)

# ---- traces: (start x,y) then polyline points, ending in a node ----
def trace(pts, node=True, w=2.5):
    d = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in pts)
    s = f'<path d="{d}" fill="none" stroke="url(#trace)" stroke-width="{w}" stroke-linejoin="round"/>'
    if node:
        x, y = pts[-1]
        s += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="6" fill="#000" stroke="{P}" stroke-width="2.5"/>'
    return s

tx = x1 + plen
lx = x0 - plen
ty = y0 - plen
by = y1 + plen
traces = [
    trace([(tx, cy + offs[0]), (tx + 70, cy + offs[0]), (tx + 70, cy + offs[0] - 60), (1160, cy + offs[0] - 60)]),
    trace([(tx, cy + offs[2]), (1135, cy + offs[2])]),
    trace([(tx, cy + offs[4]), (tx + 50, cy + offs[4]), (tx + 50, cy + offs[4] + 70), (1150, cy + offs[4] + 70)]),
    trace([(tx, cy + offs[5]), (tx + 95, cy + offs[5]), (tx + 95, cy + 175), (1100, cy + 175)]),
    trace([(cx + offs[1], ty), (cx + offs[1], 150), (1040, 150)]),
    trace([(cx + offs[4], ty), (cx + offs[4], 95), (1110, 95)]),
    trace([(cx + offs[2], by), (cx + offs[2], 560), (1000, 560)]),
    trace([(lx, cy + offs[1]), (lx - 60, cy + offs[1]), (lx - 60, cy - 120), (640, cy - 120)]),
    trace([(lx, cy + offs[5]), (lx - 45, cy + offs[5]), (lx - 45, cy + 150), (700, cy + 150)]),
    trace([(cx + offs[0], by), (cx + offs[0], 585), (800, 585)]),
]

# faint background grid
grid = []
for gx in range(0, W + 1, 60):
    grid.append(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{H}"/>')
for gy in range(0, H + 1, 60):
    grid.append(f'<line x1="0" y1="{gy}" x2="{W}" y2="{gy}"/>')
grid_svg = "\n".join(grid)

def pill(x, y, label, w):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="40" rx="20" fill="rgba(255,255,255,0.06)" '
        f'stroke="rgba(255,255,255,0.28)" stroke-width="1.5"/>'
        f'<text x="{x + w/2}" y="{y + 26}" text-anchor="middle" font-size="19" font-weight="600" '
        f'fill="#fff" letter-spacing="0.5">{label}</text>'
    )

pills = pill(80, 468, "Arduino", 112) + pill(204, 468, "ESP32", 98) + pill(314, 468, "RP2040", 112) + pill(438, 468, "RISC-V", 106)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Inter, 'Helvetica Neue', Arial, sans-serif">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#000"/>
      <stop offset="0.55" stop-color="#07010d"/>
      <stop offset="1" stop-color="#1c0230"/>
    </linearGradient>
    <radialGradient id="glowR" cx="0.76" cy="0.5" r="0.5">
      <stop offset="0" stop-color="{P}" stop-opacity="0.55"/>
      <stop offset="1" stop-color="{P}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="glowL" cx="0" cy="1" r="0.55">
      <stop offset="0" stop-color="{P}" stop-opacity="0.28"/>
      <stop offset="1" stop-color="{P}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="word" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#fff"/>
      <stop offset="0.45" stop-color="#fff"/>
      <stop offset="1" stop-color="{P}"/>
    </linearGradient>
    <linearGradient id="trace" gradientUnits="userSpaceOnUse" x1="640" y1="0" x2="1160" y2="0">
      <stop offset="0" stop-color="{P}"/>
      <stop offset="1" stop-color="#fff"/>
    </linearGradient>
    <linearGradient id="chipStroke" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#fff"/>
      <stop offset="1" stop-color="{P}"/>
    </linearGradient>
    <linearGradient id="chipFill" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#1a1a1a"/>
      <stop offset="1" stop-color="#000"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{P}"/>
      <stop offset="1" stop-color="#fff"/>
    </linearGradient>
    <filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="28"/></filter>
  </defs>

  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  <rect width="{W}" height="{H}" fill="url(#glowR)"/>
  <rect width="{W}" height="{H}" fill="url(#glowL)"/>
  <g stroke="#fff" stroke-opacity="0.045" stroke-width="1">{grid_svg}</g>

  <!-- circuit traces -->
  <g>{"".join(traces)}</g>

  <!-- chip -->
  <rect x="{x0-10}" y="{y0-10}" width="{size+20}" height="{size+20}" rx="30" fill="{P}" opacity="0.55" filter="url(#blur)"/>
  <g stroke="#fff" stroke-width="4.5" stroke-linecap="round" opacity="0.92">{pin_svg}</g>
  <rect x="{x0}" y="{y0}" width="{size}" height="{size}" rx="22" fill="url(#chipFill)" stroke="url(#chipStroke)" stroke-width="3.5"/>
  <rect x="{x0+26}" y="{y0+26}" width="{size-52}" height="{size-52}" rx="12" fill="none" stroke="{P}" stroke-opacity="0.7" stroke-width="2"/>
  <circle cx="{x0+22}" cy="{y0+22}" r="5" fill="{P}"/>
  <text x="{cx}" y="{cy+16}" text-anchor="middle" font-size="58" font-weight="800" fill="#fff" letter-spacing="-1">IoT</text>
  <text x="{cx}" y="{cy+48}" text-anchor="middle" font-size="19" font-weight="600" fill="{P}" letter-spacing="6">STUDIO</text>

  <!-- left copy -->
  <rect x="80" y="104" width="64" height="6" rx="3" fill="url(#bar)"/>
  <text x="76" y="228" font-size="112" font-weight="800" fill="url(#word)" letter-spacing="-4">IoT-Studio</text>
  <text x="80" y="306" font-size="40" font-weight="600" fill="#fff">Simulate hardware in your browser</text>
  <text x="80" y="356" font-size="26" font-weight="400" fill="#fff" fill-opacity="0.62">Code, run and debug microcontrollers —</text>
  <text x="80" y="392" font-size="26" font-weight="400" fill="#fff" fill-opacity="0.62">with SPICE-accurate analog circuits.</text>
  {pills}
  <text x="80" y="570" font-size="19" font-weight="500" fill="#fff" fill-opacity="0.45" letter-spacing="1">OPEN SOURCE  ·  AGPLv3</text>
</svg>
'''
open(sys.argv[1], "w", encoding="utf-8").write(svg)
print("wrote", sys.argv[1], len(svg), "bytes")
