// Tiny external store for the agent panel's open/closed state, so the toolbar
// launcher and the panel (mounted elsewhere) stay in sync without props.
import { useSyncExternalStore } from 'react';

let open = false;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

export function setAgentOpen(value: boolean): void {
  if (open === value) return;
  open = value;
  emit();
}

export function toggleAgent(): void {
  setAgentOpen(!open);
}

export function useAgentOpen(): boolean {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => {
        listeners.delete(cb);
      };
    },
    () => open,
    () => false,
  );
}
