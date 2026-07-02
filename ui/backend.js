// ---------------------------------------------------------------------------
// Shared backend detection — pings the FastAPI service once at startup and
// updates the header engine badge. Both Phase 1 and Phase 2 views read
// `backendState.available` and fall back to their own pure-JS engines
// per-request if a call fails mid-flight.
// ---------------------------------------------------------------------------

export const BACKEND_BASE = 'http://localhost:8000';

export const backendState = { available: false };

// Raised when the Python engine returns a genuine parse/verify error (HTTP 200
// with an `error` field). Distinct from transport failures (network/404), which
// should fall back to the JS engine — a real engine error should surface.
export class BackendEngineError extends Error {}

export async function detectBackend() {
  const engineBadge = document.getElementById('engine-badge');

  try {
    const response = await fetch(`${BACKEND_BASE}/api/parse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ir_text: '; check connection' })
    });
    if (!response.ok) throw new Error();
    backendState.available = true;
    engineBadge.textContent = 'Python Backend (Strict LLVM)';
    engineBadge.className = 'badge python';
  } catch {
    backendState.available = false;
    engineBadge.textContent = 'JS Fallback Engine (Static Site)';
    engineBadge.className = 'badge js';
  }
}

export function markFallback() {
  const engineBadge = document.getElementById('engine-badge');
  engineBadge.textContent = 'JS Fallback Engine (Static Site)';
  engineBadge.className = 'badge js';
}
