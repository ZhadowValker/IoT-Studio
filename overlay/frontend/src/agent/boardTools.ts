// Board knowledge for the agent: what a board can do and which pins carry
// which bus, so it picks the right pins and language the first time instead of
// finding out from a failed compile. Pin roles are read live from the board's
// real pin list through the same classifier the simulator routes with; the
// family notes are static and deliberately conservative.

import { useSimulatorStore } from '../store/useSimulatorStore';
import { classifyPin } from '../utils/boardProtocols';
import {
  BOARD_KIND_FQBN,
  BOARD_KIND_LABELS,
  BOARD_SUPPORTS_ESPIDF,
  BOARD_SUPPORTS_MICROPYTHON,
  isPiBoardKind,
  isStm32BoardKind,
  type BoardKind,
} from '../types/board';
import type { Tool } from './tools';

interface Family {
  family: string;
  logic: string;
  wifi: string;
  adc: string;
  notes: string[];
}

function familyOf(kind: string): Family {
  if (isPiBoardKind(kind)) {
    return {
      family: 'Raspberry Pi (Linux, QEMU on the backend)',
      logic: '3.3 V',
      wifi: 'n/a (Linux networking inside the guest)',
      adc: 'none (no analog inputs; use an external ADC over I2C/SPI)',
      notes: [
        'Runs Linux, not a sketch: programs are Python or shell scripts, not compile/upload.',
        'GPIO uses BCM numbering. The Linux terminal tools are not available to you yet, so say so if the task needs the shell.',
      ],
    };
  }
  if (isStm32BoardKind(kind)) {
    return {
      family: 'STM32 (Arm Cortex-M, QEMU on the backend)',
      logic: '3.3 V',
      wifi: 'no',
      adc: '12-bit on the analog-capable pins (PA0-PA7, PB0-PB1)',
      notes: ['Arduino core for STM32. Pin names look like PA5, PB7.'],
    };
  }
  if (kind === 'attiny85') {
    return {
      family: 'AVR ATtiny85 (browser emulation)',
      logic: '5 V (tolerates 3.3 V)',
      wifi: 'no',
      adc: '10-bit on PB2-PB5 (4 channels)',
      notes: ['Only 8 KB flash and 512 B RAM: keep sketches tiny, no Serial hardware.', 'Only 6 I/O pins, 5 usable.'],
    };
  }
  if (kind.startsWith('arduino-') && !kind.includes('esp32')) {
    return {
      family: 'AVR ATmega (browser emulation)',
      logic: '5 V',
      wifi: 'no',
      adc: kind === 'arduino-mega' ? '10-bit on A0-A15' : '10-bit on A0-A5 (A4/A5 are also I2C)',
      notes: [
        'No WiFi or Bluetooth: IoT features need an ESP32 board.',
        kind === 'arduino-uno' || kind === 'arduino-nano'
          ? 'PWM on pins 3, 5, 6, 9, 10, 11. Only 2 KB RAM, avoid big Strings.'
          : 'Several hardware serial ports (Serial1-3).',
      ],
    };
  }
  if (kind === 'raspberry-pi-pico' || kind === 'pi-pico-w') {
    return {
      family: 'RP2040 (browser emulation)',
      logic: '3.3 V',
      wifi: kind === 'pi-pico-w' ? 'chip has WiFi, but the emulator ignores it: do not build WiFi features here' : 'no',
      adc: '12-bit on GP26-GP28 (ADC0-2)',
      notes: ['Pin names are GP0..GP28. Arduino (earlephilhower core) or MicroPython.'],
    };
  }
  // ESP32 family
  const chip = kind.includes('c3') || kind.includes('supermini') ? 'ESP32-C3 (RISC-V)'
    : kind.includes('s3') || kind === 'arduino-nano-esp32' ? 'ESP32-S3 (Xtensa)' : 'ESP32 (Xtensa)';
  const classic = chip === 'ESP32 (Xtensa)';
  return {
    family: `${chip}, QEMU on the backend`,
    logic: '3.3 V (GPIOs are not 5 V tolerant)',
    wifi: 'yes, emulated; a sketch can serve pages through the IoT gateway',
    adc: classic
      ? '12-bit; use ADC1 pins (GPIO32-39). On real hardware ADC2 pins stop working while WiFi is on'
      : '12-bit on the analog-capable GPIOs',
    notes: [
      classic ? 'GPIO34-39 are input-only (no output, no internal pull-up).' : 'Check pin names with get_pins before wiring.',
      'Serial is UART0 over USB. Avoid strapping pins (GPIO0, 2, 12, 15 on the classic ESP32) for sensitive wiring.',
      'Supports Arduino, MicroPython and ESP-IDF projects.',
    ],
  };
}

function protocolPins(boardId: string, kind: string): Record<string, string[]> {
  const el = document.getElementById(boardId) as (HTMLElement & { pinInfo?: { name: string }[] }) | null;
  const out: Record<string, string[]> = {};
  for (const p of el?.pinInfo ?? []) {
    let role;
    try {
      role = classifyPin(kind, p.name);
    } catch {
      continue;
    }
    if (!role || role.kind === 'digital' || role.kind === 'power') continue;
    const bus = 'uart' in role ? `UART${role.uart}` : 'bus' in role ? (role.kind.startsWith('i2c') ? `I2C${role.bus}` : `SPI${role.bus}`) : '';
    const label = `${bus} ${role.kind.split('-')[1].toUpperCase()}`;
    (out[label] ??= []).push(p.name);
  }
  return out;
}

export const BOARD_TOOLS: Tool[] = [
  {
    name: 'get_board_info',
    description:
      'Capabilities of a board on the canvas: chip family, logic voltage, WiFi support, analog inputs, which ' +
      'pins carry I2C/SPI/UART, supported languages and build target. Call before choosing pins or libraries, ' +
      'and before promising a feature (e.g. WiFi on an Arduino Uno is impossible). Omit id for the active board.',
    parameters: { type: 'object', properties: { id: { type: 'string' } } },
    async run(args) {
      const sim = useSimulatorStore.getState();
      const id = typeof args.id === 'string' && args.id ? args.id : sim.activeBoardId;
      const b = sim.boards.find((x) => x.id === id);
      if (!b) throw new Error(`No board "${id}". Boards: ${sim.boards.map((x) => x.id).join(', ') || '(none)'}.`);
      const kind = b.boardKind as BoardKind;
      const f = familyOf(kind);
      const languages = isPiBoardKind(kind)
        ? ['python', 'shell']
        : ['arduino', ...(BOARD_SUPPORTS_MICROPYTHON.has(kind) ? ['micropython'] : []), ...(BOARD_SUPPORTS_ESPIDF.has(kind) ? ['espidf'] : [])];
      return {
        id: b.id,
        kind,
        label: BOARD_KIND_LABELS[kind] ?? kind,
        family: f.family,
        logic_level: f.logic,
        wifi: f.wifi,
        analog_inputs: f.adc,
        languages,
        current_language: b.languageMode,
        build_target: BOARD_KIND_FQBN[kind] ?? null,
        bus_pins: protocolPins(b.id, kind),
        notes: f.notes,
        libraries: 'Arduino libraries come from the project\'s libraries.json (read it with read_file) and the Libraries manager.',
      };
    },
  },
];
