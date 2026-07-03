import { BACKEND_BASE, backendState, markFallback, BackendEngineError } from './backend.js';

function renderResult(data) {
  const container = document.getElementById('verify-result-container');
  const verdict = data.verdict;
  const cex = data.counterexample;

  let tagClass = '';
  let icon = '';
  let desc = '';

  if (verdict === 'passed') {
    tagClass = 'success';
    icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/></svg>`;
    desc = 'llvm-as syntax check passed and alive-tv formally proved the candidate is a sound refinement of the original.';
  } else if (verdict === 'rejected') {
    tagClass = 'error';
    icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
    desc = 'alive-tv found a counterexample. The candidate introduces undefined behavior, alters side effects, or changes the return value.';
  } else if (verdict === 'syntax_fail') {
    tagClass = 'error';
    icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
    desc = 'The LLM generated invalid LLVM IR that failed the basic llvm-as syntax check.';
  } else {
    tagClass = 'warning';
    icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>`;
    desc = 'Verification timed out or the tools are not installed locally. Safety guardrail falls back to original IR.';
  }

  const cexBlock = cex ? `
    <div style="margin-top: 1rem;">
      <h4 style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.25rem;">Counterexample (SAT Model)</h4>
      <pre style="background: rgba(220, 38, 38, 0.1); border: 1px solid rgba(220, 38, 38, 0.2);"><code class="language-llvm" id="cex-code"></code></pre>
    </div>
  ` : '';

  container.innerHTML = `
    <div class="glass-panel result-card triage-card" style="animation-delay: 0.05s">
      <div class="card-header">
        <h3>
          ${icon}
          Verdict: <span style="text-transform: uppercase;">${verdict.replace('_', ' ')}</span>
        </h3>
        <span class="tag ${tagClass}">${verdict.toUpperCase()}</span>
      </div>
      <p class="card-desc">${desc}</p>
      ${cexBlock}
    </div>
  `;

  if (cex) {
    container.querySelector('#cex-code').textContent = cex;
  }
}

export function initPhase5() {
  const btn = document.getElementById('verify-btn');
  const originalInput = document.getElementById('verify-original-input');
  const candidateInput = document.getElementById('verify-candidate-input');
  const errorMsg = document.getElementById('verify-error-message');
  const emptyState = document.getElementById('verify-empty-state');
  const resultContainer = document.getElementById('verify-result-container');

  btn.addEventListener('click', async () => {
    const orig = originalInput.value;
    const cand = candidateInput.value;
    
    if (!orig.trim() || !cand.trim()) {
        errorMsg.textContent = "Both original and candidate IR are required.";
        errorMsg.classList.remove('hidden');
        return;
    }

    btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="animation: spin 1s linear infinite;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Verifying...`;
    btn.disabled = true;
    errorMsg.classList.add('hidden');
    emptyState.classList.add('hidden');
    resultContainer.innerHTML = '';

    try {
      if (backendState.available) {
        const response = await fetch(`${BACKEND_BASE}/api/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ original_ir: orig, candidate_ir: cand })
        });
        
        if (!response.ok) {
          throw new Error(`Backend returned ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.error) {
          throw new BackendEngineError(data.error);
        }
        
        renderResult(data);
      } else {
        // Fallback demo mode if backend is completely down
        markFallback();
        setTimeout(() => {
          renderResult({ verdict: 'unsupported', counterexample: null });
        }, 800);
      }
    } catch (err) {
      errorMsg.textContent = err.message;
      errorMsg.classList.remove('hidden');
      emptyState.classList.remove('hidden');
    } finally {
      btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/></svg> Verify Refinement`;
      btn.disabled = false;
    }
  });
}
