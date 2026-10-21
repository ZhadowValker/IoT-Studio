// Input tools: let the agent poke the running circuit the way a user would
// (press a button, turn a knob, change a sensor reading) so it can check that
// its own sketch behaves, then read the result from the serial output.

import { useSimulatorStore } from '../store/useSimulatorStore';
import { dispatchSensorUpdate, getLastSensorValues } from '../simulation/SensorUpdateRegistry';
import { getSensorControlForComponent } from '../simulation/sensorControlConfig';
import type { Tool } from './tools';

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

type Part = ReturnType<typeof useSimulatorStore.getState>['components'][number];

function part(id: string): Part {
  const c = useSimulatorStore.getState().components.find((x) => x.id === id);
  if (!c) throw new Error(`No part with id "${id}". Parts: ${useSimulatorStore.getState().components.map((x) => x.id).join(', ') || '(none)'}.`);
  return c;
}

function el(id: string): (HTMLElement & Record<string, unknown>) | null {
  return document.getElementById(id) as (HTMLElement & Record<string, unknown>) | null;
}

function isRunning(): boolean {
  return useSimulatorStore.getState().boards.some((b) => b.running);
}

const needRun = 'The simulation is not running, so this had no effect on the program. Call run first.';

function str(o: unknown, k: string): string {
  const v = (o as Record<string, unknown> | null)?.[k];
  return typeof v === 'string' ? v : '';
}

export const INPUT_TOOLS: Tool[] = [
  {
    name: 'list_controls',
    description:
      'List what can be operated on the placed parts: sensors with adjustable readings (temperature, ' +
      'distance, light...), buttons, knobs and switches, with their ranges. Use before set_sensor / ' +
      'press_button / set_input.',
    parameters: { type: 'object', properties: {} },
    async run() {
      const out: unknown[] = [];
      for (const c of useSimulatorStore.getState().components) {
        const def = getSensorControlForComponent(c);
        const tag = el(c.id)?.tagName.toLowerCase() ?? '';
        if (def) {
          out.push({
            id: c.id,
            kind: 'sensor',
            type: c.metadataId,
            controls: def.controls.map((k) =>
              k.type === 'slider'
                ? { key: k.key, min: k.min, max: k.max, unit: k.unit, now: getLastSensorValues(c.id)?.[k.key] ?? def.defaultValues[k.key] }
                : { key: k.key, action: 'trigger (use set_sensor with true)' },
            ),
          });
        } else if (/pushbutton/.test(tag)) {
          out.push({ id: c.id, kind: 'button', type: c.metadataId });
        } else if (/potentiometer|slide-pot/.test(tag)) {
          out.push({ id: c.id, kind: 'knob', type: c.metadataId, range: '0-100 (percent of travel)' });
        } else if (/switch/.test(tag)) {
          out.push({ id: c.id, kind: 'switch', type: c.metadataId, range: '0 or 1' });
        }
      }
      return { running: isRunning(), controls: out };
    },
  },
  {
    name: 'set_sensor',
    description:
      'Set sensor readings on a running simulation, e.g. {"id":"dht22_1","values":{"temperature":30,"humidity":70}}. ' +
      'Keys and ranges come from list_controls. Out-of-range values are clamped. Then use wait_for_serial or get_serial to see the effect.',
    writes: true,
    parameters: {
      type: 'object',
      properties: { id: { type: 'string' }, values: { type: 'object' } },
      required: ['id', 'values'],
    },
    async run(args) {
      const c = part(str(args, 'id'));
      const def = getSensorControlForComponent(c);
      if (!def) throw new Error(`${c.id} (${c.metadataId}) has no adjustable readings. Call list_controls.`);
      const given = (args.values ?? {}) as Record<string, unknown>;
      const applied: Record<string, number | boolean> = {};
      const warnings: string[] = [];
      for (const [k, v] of Object.entries(given)) {
        const ctl = def.controls.find((x) => x.key === k);
        if (!ctl) {
          warnings.push(`Unknown key "${k}"; valid: ${def.controls.map((x) => x.key).join(', ')}.`);
          continue;
        }
        if (ctl.type === 'button') {
          applied[k] = Boolean(v);
        } else {
          const n = Number(v);
          if (!Number.isFinite(n)) {
            warnings.push(`"${k}" must be a number.`);
            continue;
          }
          const cl = Math.min(ctl.max, Math.max(ctl.min, n));
          if (cl !== n) warnings.push(`"${k}" clamped to ${cl} (range ${ctl.min}..${ctl.max}).`);
          applied[k] = cl;
        }
      }
      if (Object.keys(applied).length) dispatchSensorUpdate(c.id, applied);
      return { id: c.id, applied, warnings, note: isRunning() ? undefined : needRun };
    },
  },
  {
    name: 'press_button',
    description: 'Press and release a push button for holdMs milliseconds (default 250, max 5000).',
    writes: true,
    parameters: {
      type: 'object',
      properties: { id: { type: 'string' }, holdMs: { type: 'number' } },
      required: ['id'],
    },
    async run(args) {
      const c = part(str(args, 'id'));
      const e = el(c.id);
      if (!e || !/pushbutton|button/.test(e.tagName.toLowerCase())) throw new Error(`${c.id} is not a button. Call list_controls.`);
      const hold = Math.min(5000, Math.max(30, Number(args.holdMs) || 250));
      e.dispatchEvent(new CustomEvent('button-press', { detail: { keyboard: false } }));
      await sleep(hold);
      e.dispatchEvent(new CustomEvent('button-release', { detail: { keyboard: false } }));
      await sleep(60);
      return { id: c.id, pressedForMs: hold, note: isRunning() ? undefined : needRun };
    },
  },
  {
    name: 'set_input',
    description: 'Turn a knob (potentiometer, 0-100 percent of travel) or flip a switch (0 or 1).',
    writes: true,
    parameters: {
      type: 'object',
      properties: { id: { type: 'string' }, value: { type: 'number' } },
      required: ['id', 'value'],
    },
    async run(args) {
      const c = part(str(args, 'id'));
      const e = el(c.id);
      const tag = e?.tagName.toLowerCase() ?? '';
      if (!e || !/potentiometer|slide-pot|switch/.test(tag)) throw new Error(`${c.id} is not a knob or switch. Call list_controls.`);
      const isKnob = /potentiometer|slide-pot/.test(tag);
      const v = isKnob ? Math.min(100, Math.max(0, Number(args.value))) : Number(args.value) ? 1 : 0;
      if (!Number.isFinite(v)) throw new Error('value must be a number.');
      e.value = v;
      e.dispatchEvent(new Event('input', { bubbles: true }));
      e.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(80);
      return { id: c.id, value: v, note: isRunning() ? undefined : needRun };
    },
  },
];
