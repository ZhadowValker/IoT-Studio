// Pure planning for undoing the simulation side of an agent turn. Kept free of
// app imports so it can be unit-tested; tools.ts carries the plan out.

export interface BoardSnap {
  id: string;
  running: boolean;
  serial: string;
  program: unknown; // compiledProgram, compared by identity
}

export interface RestorePlan {
  stopFirst: boolean;
  /** boards whose serial log and compiled program go back to the snapshot */
  restore: string[];
  notes: string[];
}

export function planSimRestore(before: BoardSnap[], now: BoardSnap[], label: (id: string) => string): RestorePlan {
  const notes: string[] = [];
  const restore: string[] = [];
  let stopFirst = false;
  for (const b of before) {
    const n = now.find((x) => x.id === b.id);
    if (!n) continue; // board removed since; nothing to put back
    const programChanged = n.program !== b.program;
    const serialChanged = n.serial !== b.serial;
    if (n.running && (programChanged || !b.running)) {
      // Running something the turn started or compiled: it no longer matches the restored files.
      stopFirst = true;
      notes.push(`${label(b.id)} was stopped (the turn had started or rebuilt it).`);
    }
    if (programChanged || serialChanged) restore.push(b.id);
    if (programChanged) notes.push(`${label(b.id)}: the earlier compiled program is back.`);
    if (b.running && !n.running) notes.push(`${label(b.id)} was running before the turn: press Run to start it again.`);
  }
  // A board that did not exist at the checkpoint is left alone: boards are never added or removed by the agent.
  return { stopFirst, restore, notes };
}
