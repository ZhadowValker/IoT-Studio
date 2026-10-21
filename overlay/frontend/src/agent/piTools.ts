// Raspberry Pi tools: a shell inside the emulated Linux guest, so the agent can
// install nothing it cannot see but can run scripts, read GPIO state, check
// i2cdetect output and so on. Only for the QEMU-Linux boards.

import { getBoardBridge, useSimulatorStore } from '../store/useSimulatorStore';
import { uploadFilesToPi } from '../utils/piUpload';
import { isPiBoardKind } from '../types/board';
import { runShell, type ShellBridge } from './piCore';
import type { Tool } from './tools';

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function piBoard(id: unknown) {
  const sim = useSimulatorStore.getState();
  const want = typeof id === 'string' && id ? id : '';
  const b = want
    ? sim.boards.find((x) => x.id === want)
    : sim.boards.find((x) => x.id === sim.activeBoardId && isPiBoardKind(x.boardKind)) ??
      sim.boards.find((x) => isPiBoardKind(x.boardKind));
  if (!b || !isPiBoardKind(b.boardKind)) {
    throw new Error('There is no Raspberry Pi board on the canvas. These tools only work on Raspberry Pi boards.');
  }
  return b;
}

function liveBridge(id: unknown) {
  const b = piBoard(id);
  const bridge = getBoardBridge(b.id);
  if (!b.running || !bridge || !bridge.connected) {
    throw new Error(`${b.id} is not running. Call run to start it; Linux takes 30-60 s to boot, then call pi_wait_boot.`);
  }
  if (!b.piBooted) throw new Error(`${b.id} is still booting. Call pi_wait_boot.`);
  return { board: b, bridge };
}

export const PI_TOOLS: Tool[] = [
  {
    name: 'pi_wait_boot',
    description: 'Wait (up to timeoutSec, max 120) for the Raspberry Pi guest to finish booting and show a shell.',
    parameters: { type: 'object', properties: { id: { type: 'string' }, timeoutSec: { type: 'number' } } },
    async run(args, signal) {
      const b0 = piBoard(args.id);
      const limit = Math.min(120, Math.max(5, Number(args.timeoutSec) || 90)) * 1000;
      const t0 = Date.now();
      while (Date.now() - t0 < limit) {
        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
        const b = useSimulatorStore.getState().boards.find((x) => x.id === b0.id);
        if (b?.running && b.piBooted) return { booted: true, waitedSec: Math.round((Date.now() - t0) / 1000) };
        await sleep(500);
      }
      const b = useSimulatorStore.getState().boards.find((x) => x.id === b0.id);
      return { booted: false, running: Boolean(b?.running), note: b?.running ? 'Still booting; try again.' : 'The board is not running. Call run first.' };
    },
  },
  {
    name: 'pi_run',
    description:
      'Run ONE single-line shell command in the Raspberry Pi guest and get its output and exit code. ' +
      'Whatever is running in the foreground (such as the project script) is interrupted first, so call run ' +
      'again afterwards to restart it. For multi-line scripts use pi_write_file then run the file. ' +
      'timeoutSec defaults to 20, max 120.',
    writes: true,
    parameters: {
      type: 'object',
      properties: { command: { type: 'string' }, timeoutSec: { type: 'number' }, id: { type: 'string' } },
      required: ['command'],
    },
    async run(args, signal) {
      const { bridge } = liveBridge(args.id);
      const cmd = typeof args.command === 'string' ? args.command : '';
      if (!cmd.trim()) throw new Error('Give a command.');
      const ms = Math.min(120, Math.max(2, Number(args.timeoutSec) || 20)) * 1000;
      return runShell(bridge as unknown as ShellBridge, cmd, ms, signal);
    },
  },
  {
    name: 'pi_write_file',
    description:
      'Write a text file inside the Raspberry Pi guest (for example /home/pi/test.py). Parent folders are created; ' +
      '.py and .sh files are made executable.',
    writes: true,
    parameters: {
      type: 'object',
      properties: { path: { type: 'string' }, content: { type: 'string' }, id: { type: 'string' } },
      required: ['path', 'content'],
    },
    async run(args) {
      const { bridge } = liveBridge(args.id);
      const path = typeof args.path === 'string' ? args.path.trim() : '';
      if (!path.startsWith('/') || /[\s'"`$;&|<>]/.test(path)) throw new Error('Use a plain absolute path such as /home/pi/test.py.');
      const content = typeof args.content === 'string' ? args.content : '';
      if (content.length > 40000) throw new Error('File too large for the console upload (40 KB max).');
      await uploadFilesToPi(bridge, [{ path, content }]);
      return { written: path, bytes: content.length };
    },
  },
];
