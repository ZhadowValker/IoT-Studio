// Free-space placement for parts the agent adds. Pure geometry here (testable
// without the app); the DOM measuring lives in circuitTools.ts. The idea of
// choosing the board side nearest the target pin and scanning for a free slot
// follows velxio-agentic's canvas layout engine; sizes are measured, not assumed.

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type Side = 'right' | 'left' | 'top' | 'bottom';

export const MARGIN = 40; // board edge -> first part
export const GAP = 18; // between parts

export function overlaps(a: Rect, b: Rect, pad = GAP / 2): boolean {
  return !(a.x + a.w + pad <= b.x || a.x >= b.x + b.w + pad || a.y + a.h + pad <= b.y || a.y >= b.y + b.h + pad);
}

/** Which edge of the board a pin (in the board's own coordinates) is nearest. */
export function sideOfPin(pin: { x: number; y: number }, size: { w: number; h: number }): Side {
  const d: [Side, number][] = [
    ['left', pin.x],
    ['right', size.w - pin.x],
    ['top', pin.y],
    ['bottom', size.h - pin.y],
  ];
  d.sort((a, b) => a[1] - b[1]);
  return d[0][0];
}

/** First position for a w x h part beside `board` on `side` that touches none of
 *  `occupied`. Fills the column next to the board top to bottom (or the row
 *  left to right), then moves outward, so related parts stay close. */
export function findFreeSlot(board: Rect, side: Side, w: number, h: number, occupied: Rect[]): { x: number; y: number } {
  const vertical = side === 'left' || side === 'right';
  for (let ring = 0; ring < 12; ring++) {
    const out = MARGIN + ring * (vertical ? w + GAP : h + GAP);
    const lane =
      side === 'right' ? board.x + board.w + out
      : side === 'left' ? board.x - out - w
      : side === 'bottom' ? board.y + board.h + out
      : board.y - out - h;
    const span = vertical ? board.h + 200 : board.w + 200;
    const start = vertical ? board.y - 20 : board.x - 20;
    const step = (vertical ? h : w) + GAP;
    for (let off = 0; off * step < span; off++) {
      const p = vertical ? { x: lane, y: start + off * step } : { x: start + off * step, y: lane };
      if (!occupied.some((r) => overlaps({ ...p, w, h }, r))) return p;
    }
  }
  // Everything near the board is taken: park below the lowest thing on the canvas.
  const bottom = Math.max(board.y + board.h, ...occupied.map((r) => r.y + r.h));
  return { x: board.x, y: bottom + MARGIN };
}
