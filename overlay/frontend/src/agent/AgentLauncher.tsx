import { toggleAgent, useAgentOpen } from './agentUi';

// Toolbar button that opens the IoT-Studio AI agent panel. Rendered next to
// the "Add" button in the simulator header; reuses the header's button class
// so it matches Serial / Scope.
export function AgentLauncher() {
  const open = useAgentOpen();
  return (
    <button
      type="button"
      className={`canvas-serial-btn${open ? ' canvas-serial-btn-active' : ''}`}
      onClick={toggleAgent}
      aria-pressed={open}
      title="IoT-Studio AI agent"
    >
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
        <path d="M19 15l.7 1.8L21.5 17.5l-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7L19 15z" />
      </svg>
      AI agent
    </button>
  );
}

export default AgentLauncher;
