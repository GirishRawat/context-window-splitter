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
    icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #4ade80"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`;
    desc = 'llvm-as syntax check passed and alive-tv formally proved the candidate is a sound refinement of the original.';
  } else if (verdict === 'rejected') {
    tagClass = 'error';
    icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #f87171"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
    desc = 'alive-tv found a counterexample. The candidate introduces undefined behavior, alters side effects, or changes the return value.';
  } else if (verdict === 'syntax_fail') {
    tagClass = 'error';
    icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #f87171"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;
    desc = 'The LLM generated invalid LLVM IR that failed the basic llvm-as syntax check.';
  } else {
    tagClass = 'warning';
    icon = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #eab308"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`;
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

const EXAMPLES = [
  {
    orig: `define i32 @test(i32 %a) {
entry:
  %add = add i32 0, %a
  %add1 = add i32 %add, 0
  ret i32 %add1
}`,
    cand: `define i32 @test(i32 %a) {
entry:
  ret i32 %a
}`
  },
  {
    orig: `define i32 @add_overflow(i32 %a) {
entry:
  %add = add i32 %a, 1
  ret i32 %add
}`,
    cand: `define i32 @add_overflow(i32 %a) {
entry:
  %add = add nsw i32 %a, 1
  ret i32 %add
}`
  },
  {
    orig: `define i32 @shift_mul(i32 %a) {
entry:
  %mul = mul i32 %a, 4
  ret i32 %mul
}`,
    cand: `define i32 @shift_mul(i32 %a) {
entry:
  %shl = shl i32 %a, 2
  ret i32 %shl
}`
  }
];

export function initPhase5() {
  const btn = document.getElementById('verify-btn');
  const originalInput = document.getElementById('verify-original-input');
  const candidateInput = document.getElementById('verify-candidate-input');
  const errorMsg = document.getElementById('verify-error-message');
  const emptyState = document.getElementById('verify-empty-state');
  const resultContainer = document.getElementById('verify-result-container');
  const exampleBtn = document.getElementById('phase5-example-btn');

  let currentIdx = 0;
  exampleBtn.addEventListener('click', () => {
    currentIdx = (currentIdx + 1) % EXAMPLES.length;
    originalInput.value = EXAMPLES[currentIdx].orig;
    candidateInput.value = EXAMPLES[currentIdx].cand;
  });

  btn.addEventListener('click', async () => {
    const orig = originalInput.value;
    const cand = candidateInput.value;
    
    if (!orig.trim() || !cand.trim()) {
        errorMsg.textContent = "Both original and candidate IR are required.";
        errorMsg.classList.remove('hidden');
        return;
    }

    btn.innerHTML = ` Verifying...`;
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
      btn.innerHTML = ` Verify Refinement`;
      btn.disabled = false;
    }
  });
}
