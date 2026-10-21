// Circuit tools: find parts, place them, read their pins, wire them up.
// They drive the same stores and helpers the canvas uses (the component
// factory, the pin position calculator, the wire-creation flow with its
// obstacle routing), so what the agent builds looks like what a user builds.

import { ComponentRegistry } from '../services/ComponentRegistry';
import { createComponentFromMetadata } from '../components/DynamicComponent';
import { useSimulatorStore } from '../store/useSimulatorStore';
import { calculatePinPosition } from '../utils/pinPositionCalculator';
import { findFreeSlot, sideOfPin, type Rect, type Side } from './placement';
import type { Tool } from './tools';

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

interface PinInfo {
  name: string;
  description?: string;
}

function anyRunning(): boolean {
  return useSimulatorStore.getState().boards.some((b) => b.running);
}

function assertStopped(): void {
  if (anyRunning()) {
    throw new Error('The simulation is running, so the circuit is read-only. Call stop first, edit, then run again.');
  }
}

/** Where an item's inner element sits: components carry a 6 px wrapper offset,
 *  boards are rendered directly. */
function locate(id: string): { x: number; y: number; rotation: number; isBoard: boolean } | null {
  const s = useSimulatorStore.getState();
  const board = s.boards.find((b) => b.id === id);
  if (board) return { x: board.x, y: board.y, rotation: 0, isBoard: true };
  const comp = s.components.find((c) => c.id === id);
  if (comp) {
    return {
      x: comp.x + 6,
      y: comp.y + 6,
      rotation: Number((comp.properties as Record<string, unknown>)?.rotation) || 0,
      isBoard: false,
    };
  }
  return null;
}

function pinsOf(id: string): PinInfo[] | null {
  const el = document.getElementById(id) as (HTMLElement & { pinInfo?: PinInfo[] }) | null;
  const info = el?.pinInfo;
  return Array.isArray(info) ? info : null;
}

/** Candidate spellings for a requested pin: boards name GPIO pins "4" while
 *  people (and models) write GPIO4, IO4, D4; ground may be GND, GND2, GND.1. */
function pinAliases(pin: string): string[] {
  const out = [pin];
  const m = pin.match(/^(?:GPIO|IO|D|P)?_?(\d+)$/i);
  if (m) out.push(m[1], `D${m[1]}`, `GPIO${m[1]}`, `IO${m[1]}`);
  const g = pin.match(/^(GND|GROUND)[.\-_ ]?(\d*)$/i);
  if (g) {
    const n = g[2] ? parseInt(g[2], 10) : 0;
    out.push('GND', `GND.${n || 1}`, `GND${n + 1}`, `GND${n || ''}`);
  }
  if (/^(3\.?3V?|3V3)$/i.test(pin)) out.push('3V3', '3.3V', '3V3.1');
  if (/^(5V|VCC|VIN)$/i.test(pin)) out.push('5V', 'VIN', 'VCC');
  return out;
}

function resolvePin(id: string, pin: string): string | null {
  const pins = pinsOf(id);
  if (!pins) return null;
  for (const cand of pinAliases(pin)) {
    const hit = pins.find((p) => p.name === cand) ?? pins.find((p) => p.name.toLowerCase() === cand.toLowerCase());
    if (hit) return hit.name;
  }
  return null;
}

function str(o: unknown, k: string): string {
  const v = (o as Record<string, unknown> | null)?.[k];
  return typeof v === 'string' ? v : '';
}

async function waitForMount(id: string): Promise<void> {
  for (let i = 0; i < 20; i++) {
    if (pinsOf(id)) return;
    await sleep(100);
  }
}

/** Canvas zoom: screen size / layout size of a board (1 when unknown). */
function canvasZoom(): number {
  const s = useSimulatorStore.getState();
  for (const b of s.boards) {
    const el = document.getElementById(b.id);
    if (el && el.offsetWidth > 0) {
      const z = el.getBoundingClientRect().width / el.offsetWidth;
      if (z > 0.05 && z < 20) return z;
    }
  }
  return 1;
}

/** Union of the on-screen boxes of an element and everything drawn inside it,
 *  shadow DOM included. Some parts (the DHT sensors, for one) report a tiny box
 *  but paint a much larger body around it, so the element's own size lies. */
function paintedBox(root: Element): DOMRect {
  let box = root.getBoundingClientRect();
  let l = box.left, t = box.top, r = box.right, b = box.bottom;
  let seen = 0;
  const walk = (node: Element) => {
    if (seen++ > 600) return;
    const q = node.getBoundingClientRect();
    if (q.width > 0 && q.height > 0) {
      l = Math.min(l, q.left); t = Math.min(t, q.top); r = Math.max(r, q.right); b = Math.max(b, q.bottom);
    }
    for (const k of Array.from(node.children)) walk(k);
    if (node.shadowRoot) for (const k of Array.from(node.shadowRoot.children)) walk(k);
  };
  walk(root);
  return new DOMRect(l, t, r - l, b - t);
}

/** Where a thing is actually painted, in canvas (store) coordinates. The screen
 *  box is mapped back through a board, whose element origin IS its store x/y, so
 *  this is right however a part positions its own wrapper or paints outside its
 *  element, and whatever the zoom and pan are. */
function paintedRect(id: string): Rect | null {
  const el = document.getElementById(id);
  const s = useSimulatorStore.getState();
  const ref = s.boards.find((b) => {
    const e = document.getElementById(b.id);
    return e && e.offsetWidth > 0;
  });
  const refEl = ref ? document.getElementById(ref.id) : null;
  if (!el || !ref || !refEl) return null;
  const z = canvasZoom();
  const o = refEl.getBoundingClientRect();
  const p = paintedBox(el);
  return {
    x: ref.x + (p.left - o.left) / z,
    y: ref.y + (p.top - o.top) / z,
    w: Math.max(el.offsetWidth, p.width / z),
    h: Math.max(el.offsetHeight, p.height / z),
  };
}

const PAD = 6;

/** Rectangles already taken on the canvas: boards and parts as painted, padded. */
function occupiedRects(except: string): Rect[] {
  const s = useSimulatorStore.getState();
  const out: Rect[] = [];
  for (const b of s.boards) {
    const r = paintedRect(b.id);
    out.push(r ?? { x: b.x, y: b.y, w: 200, h: 200 });
  }
  for (const c of s.components) {
    if (c.id === except) continue;
    const r = paintedRect(c.id) ?? { x: c.x, y: c.y, w: 60, h: 60 };
    out.push({ x: r.x - PAD, y: r.y - PAD, w: r.w + 2 * PAD, h: r.h + 2 * PAD });
  }
  return out;
}

/** Where a freshly mounted part should go: beside the board, on the side of its
 *  target pin, in the first free slot that fits its painted size. Returns the
 *  new store x/y for the part, or null when it cannot be measured yet. */
function freeSpotFor(id: string, boardId: string | undefined, side: Side | undefined, nearPin: string | undefined) {
  const s = useSimulatorStore.getState();
  const board = s.boards.find((b) => b.id === boardId) ?? s.boards.find((b) => b.id === s.activeBoardId) ?? s.boards[0];
  const comp = s.components.find((c) => c.id === id);
  const me = paintedRect(id);
  const br = board ? paintedRect(board.id) : null;
  if (!board || !comp || !me || !br) return null;
  let sd: Side = side ?? 'right';
  if (!side && nearPin) {
    const real = resolvePin(board.id, nearPin);
    const pin = (document.getElementById(board.id) as (HTMLElement & { pinInfo?: { name: string; x: number; y: number }[] }) | null)
      ?.pinInfo?.find((p) => p.name === real);
    if (pin) sd = sideOfPin(pin, { w: br.w, h: br.h });
  }
  const p = findFreeSlot(br, sd, me.w + 2 * PAD, me.h + 2 * PAD, occupiedRects(id));
  // Move the part by however far its painted box has to travel.
  return { x: Math.round(comp.x + (p.x + PAD - me.x)), y: Math.round(comp.y + (p.y + PAD - me.y)), size: { w: me.w, h: me.h } };
}

interface Endpoint {
  id: string;
  pin: string;
}

function endpoint(raw: unknown, label: string): Endpoint {
  const id = str(raw, 'id');
  const pin = str(raw, 'pin');
  if (!id || !pin) throw new Error(`${label} needs {"id": ..., "pin": ...}.`);
  return { id, pin };
}

export const CIRCUIT_TOOLS: Tool[] = [
  {
    name: 'search_components',
    description:
      'Search the part catalog (LEDs, resistors, sensors, displays, buttons, motors...). Returns ids ' +
      'to pass to add_component. Use short keywords, e.g. "dht", "led", "servo".',
    parameters: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] },
    async run(args) {
      const reg = ComponentRegistry.getInstance();
      await reg.load();
      const q = str(args, 'query').trim();
      const ql = q.toLowerCase();
      const hits = (q ? reg.search(q) : reg.getAllComponents())
        .slice()
        .sort((a, b) => Number(b.id.toLowerCase() === ql || b.name.toLowerCase() === ql) - Number(a.id.toLowerCase() === ql || a.name.toLowerCase() === ql));
      return hits.slice(0, 15).map((m) => ({
        id: m.id,
        name: m.name,
        category: m.category,
        pins: m.pinCount,
        description: (m.description ?? '').slice(0, 120),
      }));
    },
  },
  {
    name: 'add_component',
    description:
      'Place a part on the canvas next to the board. Returns its id and its exact pin names. ' +
      'Placement is automatic and never overlaps; pass near_pin (the board pin it will connect to) or side to choose the side. Never pass x/y unless the user asked for a position. The simulation must be stopped.',
    writes: true,
    parameters: {
      type: 'object',
      properties: {
        type: { type: 'string', description: 'Catalog id from search_components.' },
        properties: { type: 'object', description: 'Optional property overrides, e.g. {"color":"red"}.' },
        side: { type: 'string', description: 'Optional: left, right, top or bottom of the board.' },
        near_pin: { type: 'string', description: 'Optional: board pin this part will connect to; it is placed on that pin\'s side.' },
        board: { type: 'string', description: 'Optional board id when there are several.' },
        x: { type: 'number' },
        y: { type: 'number' },
      },
      required: ['type'],
    },
    async run(args) {
      assertStopped();
      const reg = ComponentRegistry.getInstance();
      await reg.load();
      const meta = reg.getById(str(args, 'type'));
      if (!meta) throw new Error(`Unknown part "${str(args, 'type')}". Use search_components first.`);
      const explicit = typeof args.x === 'number' && typeof args.y === 'number';
      // Mount first at a spot clear of the board, measure it, then settle it into free space.
      const comp = createComponentFromMetadata(meta, explicit ? (args.x as number) : -400, explicit ? (args.y as number) : -400);
      if (args.properties && typeof args.properties === 'object') {
        Object.assign(comp.properties, args.properties as Record<string, unknown>);
      }
      useSimulatorStore.getState().addComponent(comp);
      await waitForMount(comp.id);
      let placedAt = { x: comp.x, y: comp.y };
      if (!explicit) {
        const sd = str(args, 'side').toLowerCase();
        const side = (['left', 'right', 'top', 'bottom'] as const).find((v) => v === sd);
        const bd = str(args, 'board') || undefined;
        const np = str(args, 'near_pin') || undefined;
        // Parts finish laying out a moment after they mount (images, shadow DOM);
        // measure, settle, and re-measure at the new spot: some parts paint differently
        // once placed (the DHT's body moves), so the final box is what counts.
        let last = '';
        for (let pass = 0; pass < 4; pass++) {
          await sleep(150);
          const spot = freeSpotFor(comp.id, bd, side, np);
          if (!spot) continue;
          const sig = `${spot.x},${spot.y}`;
          if (sig === last) break;
          last = sig;
          placedAt = { x: spot.x, y: spot.y };
          useSimulatorStore.getState().updateComponent(comp.id, placedAt);
        }
      }
      return { id: comp.id, type: meta.id, at: placedAt, pins: (pinsOf(comp.id) ?? []).map((p) => p.name) };
    },
  },
  {
    name: 'get_pins',
    description:
      'Exact pin names of a placed part or a board (use these names in connect_pins). Boards have many pins; ' +
      'pass a filter such as "GPIO4" or "3V3" to narrow the list.',
    parameters: {
      type: 'object',
      properties: { id: { type: 'string' }, filter: { type: 'string' } },
      required: ['id'],
    },
    async run(args) {
      const id = str(args, 'id');
      const pins = pinsOf(id);
      if (!pins) throw new Error(`"${id}" was not found on the canvas (or has no pins yet).`);
      const f = str(args, 'filter').toLowerCase();
      const fs = f ? pinAliases(str(args, 'filter')).map((x) => x.toLowerCase()) : [];
      const out = pins
        .filter((p) => !f || fs.includes(p.name.toLowerCase()) || p.name.toLowerCase().includes(f) || (p.description ?? '').toLowerCase().includes(f))
        .slice(0, 80)
        .map((p) => (p.description && p.description !== p.name ? `${p.name} (${p.description.slice(0, 40)})` : p.name));
      return { id, count: pins.length, pins: out, note: 'Boards name GPIO pins by number (GPIO4 is "4"); either spelling works in connect_pins.' };
    },
  },
  {
    name: 'connect_pins',
    description:
      'Draw wires between pins, as a batch. Each item: {"from":{"id","pin"},"to":{"id","pin"},"color"?}. ' +
      'Pin names must come from get_pins / add_component. Wire colours are chosen automatically from the pin ' +
      'name (red power, black ground...) unless you pass one. Simulation must be stopped.',
    writes: true,
    parameters: {
      type: 'object',
      properties: {
        wires: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              from: { type: 'object', properties: { id: { type: 'string' }, pin: { type: 'string' } } },
              to: { type: 'object', properties: { id: { type: 'string' }, pin: { type: 'string' } } },
              color: { type: 'string' },
            },
          },
        },
      },
      required: ['wires'],
    },
    async run(args) {
      assertStopped();
      const list = Array.isArray(args.wires) ? (args.wires as unknown[]) : [];
      if (!list.length) throw new Error('Send at least one wire.');
      const done: string[] = [];
      const errors: string[] = [];
      for (const w of list.slice(0, 40)) {
        try {
          const a = endpoint((w as Record<string, unknown>).from, 'from');
          const b = endpoint((w as Record<string, unknown>).to, 'to');
          const sides = [a, b].map((e) => {
            const loc = locate(e.id);
            if (!loc) throw new Error(`"${e.id}" is not on the canvas.`);
            const pin = resolvePin(e.id, e.pin);
            if (!pin) {
              const names = (pinsOf(e.id) ?? []).map((p) => p.name);
              const near = names.filter((n) => n.toLowerCase().includes(e.pin.toLowerCase().slice(0, 3))).slice(0, 8);
              throw new Error(`${e.id} has no pin "${e.pin}". ${near.length ? 'Similar: ' + near.join(', ') : 'Call get_pins.'}`);
            }
            const pos = calculatePinPosition(e.id, pin, loc.x, loc.y, loc.rotation);
            if (!pos) throw new Error(`Could not locate pin ${e.id}.${pin} on the canvas yet.`);
            return { componentId: e.id, pinName: pin, x: pos.x, y: pos.y };
          });
          const s = useSimulatorStore.getState();
          const dup = s.wires.some(
            (x) =>
              (x.start.componentId === sides[0].componentId && x.start.pinName === sides[0].pinName &&
                x.end.componentId === sides[1].componentId && x.end.pinName === sides[1].pinName) ||
              (x.end.componentId === sides[0].componentId && x.end.pinName === sides[0].pinName &&
                x.start.componentId === sides[1].componentId && x.start.pinName === sides[1].pinName),
          );
          if (dup) {
            done.push(`${a.id}.${sides[0].pinName} - ${b.id}.${sides[1].pinName} (already connected)`);
            continue;
          }
          const color = str(w, 'color') || '#22c55e'; // the canvas default; finishWireCreation auto-colours it
          s.startWireCreation(sides[0], color);
          useSimulatorStore.getState().finishWireCreation(sides[1]);
          done.push(`${a.id}.${sides[0].pinName} - ${b.id}.${sides[1].pinName}`);
        } catch (e) {
          useSimulatorStore.getState().cancelWireCreation();
          errors.push((e as Error).message);
        }
      }
      return { connected: done, errors };
    },
  },
  {
    name: 'disconnect_pins',
    description: 'Remove the wire(s) between two pins.',
    writes: true,
    parameters: {
      type: 'object',
      properties: {
        from: { type: 'object', properties: { id: { type: 'string' }, pin: { type: 'string' } } },
        to: { type: 'object', properties: { id: { type: 'string' }, pin: { type: 'string' } } },
      },
      required: ['from', 'to'],
    },
    async run(args) {
      assertStopped();
      const a = endpoint(args.from, 'from');
      const b = endpoint(args.to, 'to');
      const s = useSimulatorStore.getState();
      const match = (e: { componentId: string; pinName: string }, p: Endpoint) =>
        e.componentId === p.id && e.pinName.toLowerCase().replace(/\.1$/, '') === p.pin.toLowerCase().replace(/\.1$/, '');
      const victims = s.wires.filter(
        (w) => (match(w.start, a) && match(w.end, b)) || (match(w.start, b) && match(w.end, a)),
      );
      victims.forEach((w) => useSimulatorStore.getState().removeWire(w.id));
      return { removed: victims.length };
    },
  },
  {
    name: 'remove_component',
    description: 'Remove a part (and its wires) from the canvas.',
    writes: true,
    parameters: { type: 'object', properties: { id: { type: 'string' } }, required: ['id'] },
    async run(args) {
      assertStopped();
      const id = str(args, 'id');
      const s = useSimulatorStore.getState();
      if (!s.components.some((c) => c.id === id)) throw new Error(`No part with id "${id}" (boards cannot be removed by the agent).`);
      s.removeComponent(id);
      return { removed: id };
    },
  },
  {
    name: 'set_component_property',
    description: 'Change properties of a placed part, e.g. {"color":"green"} for an LED or {"value":"220"} for a resistor.',
    writes: true,
    parameters: {
      type: 'object',
      properties: { id: { type: 'string' }, properties: { type: 'object' } },
      required: ['id', 'properties'],
    },
    async run(args) {
      assertStopped();
      const id = str(args, 'id');
      const s = useSimulatorStore.getState();
      const comp = s.components.find((c) => c.id === id);
      if (!comp) throw new Error(`No part with id "${id}".`);
      s.updateComponent(id, { properties: { ...comp.properties, ...(args.properties as Record<string, unknown>) } } as never);
      return { ok: true, id };
    },
  },
  {
    name: 'validate_circuit',
    description:
      'Check the circuit for common mistakes: parts with no wires, power or ground pins left unconnected, ' +
      'wires pointing at missing parts. Run it before telling the user the circuit is done.',
    parameters: { type: 'object', properties: {} },
    async run() {
      const s = useSimulatorStore.getState();
      const issues: string[] = [];
      const wired = new Set<string>();
      for (const w of s.wires) {
        for (const e of [w.start, w.end]) {
          wired.add(`${e.componentId}|${e.pinName}`);
          if (!locate(e.componentId)) issues.push(`A wire points at a missing part: ${e.componentId}.`);
        }
      }
      const power = /^(vcc|vdd|v\+|5v|3v3|3\.3v|vin|gnd)/i;
      for (const c of s.components) {
        const pins = pinsOf(c.id);
        const any = s.wires.some((w) => w.start.componentId === c.id || w.end.componentId === c.id);
        if (!any) {
          issues.push(`${c.id} (${c.metadataId}) has no wires.`);
          continue;
        }
        for (const p of pins ?? []) {
          if (power.test(p.name) && !wired.has(`${c.id}|${p.name}`)) {
            issues.push(`${c.id}.${p.name} (power/ground) is not connected.`);
          }
        }
      }
      return { parts: s.components.length, wires: s.wires.length, ok: issues.length === 0, issues: issues.slice(0, 25) };
    },
  },
];
