import { BACKEND_BASE, backendState, markFallback, BackendEngineError } from './backend.js';

const EXAMPLE_MODULE = {
  preamble: `source_filename = "example.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"`,
  
  fn1_orig: `define i32 @test(i32 %a) {
entry:
  %add = add i32 0, %a
  %add1 = add i32 %add, 0
  ret i32 %add1
}`,
  fn1_cand: `define i32 @test(i32 %a) {
entry:
  ret i32 %a
}`,
  
  fn2_orig: `define i32 @shift_mul(i32 %a) {
entry:
  %mul = mul i32 %a, 4
  ret i32 %mul
}`,
  fn2_cand: `define i32 @shift_mul(i32 %a) {
entry:
  %shl = shl i32 %a, 2
  ret i32 %shl
}`
};

export function initPhase6() {
  const btn = document.getElementById('assemble-btn');
  const preambleInput = document.getElementById('assemble-preamble');
  
  const fn1Orig = document.getElementById('assemble-fn1-orig');
  const fn1Cand = document.getElementById('assemble-fn1-cand');
  const fn1Verdict = document.getElementById('assemble-fn1-verdict');
  
  const fn2Orig = document.getElementById('assemble-fn2-orig');
  const fn2Cand = document.getElementById('assemble-fn2-cand');
  const fn2Verdict = document.getElementById('assemble-fn2-verdict');
  
  const errorMsg = document.getElementById('assemble-error-message');
  const emptyState = document.getElementById('assemble-empty-state');
  const resultContainer = document.getElementById('assemble-result-container');
  const outputBlock = document.getElementById('assemble-output-block');
  const outputCode = document.getElementById('assemble-output-code');

  // Set default values
  preambleInput.value = EXAMPLE_MODULE.preamble;
  fn1Orig.value = EXAMPLE_MODULE.fn1_orig;
  fn1Cand.value = EXAMPLE_MODULE.fn1_cand;
  fn2Orig.value = EXAMPLE_MODULE.fn2_orig;
  fn2Cand.value = EXAMPLE_MODULE.fn2_cand;

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    btn.textContent = 'Assembling...';
    errorMsg.classList.add('hidden');
    emptyState.classList.add('hidden');
    resultContainer.innerHTML = '';
    outputBlock.classList.add('hidden');
    outputCode.textContent = '';

    try {
      const payload = {
        preamble: preambleInput.value,
        functions: [
          {
            name: "test",
            original_ir: fn1Orig.value,
            llm_output: fn1Cand.value,
            verdict: fn1Verdict.value
          },
          {
            name: "shift_mul",
            original_ir: fn2Orig.value,
            llm_output: fn2Cand.value,
            verdict: fn2Verdict.value
          }
        ]
      };

      const resp = await fetch(`${BACKEND_BASE}/api/assemble`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.error || 'Server returned an error');
      }
      if (data.error) {
        throw new Error(data.error);
      }

      // Render the result
      outputCode.textContent = data.final_module_ir;
      outputBlock.classList.remove('hidden');
      
      // We can use a lightweight library for syntax highlighting if present, 
      // but for now just raw text or rely on Prism if it's imported globally.
      if (window.Prism) {
        window.Prism.highlightElement(outputCode);
      }

      resultContainer.innerHTML = `
        <div class="glass-panel result-card success" style="animation-delay: 0.05s">
          <div class="card-header">
            <h3>
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #4ade80"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
              Module Assembled Successfully
            </h3>
            <span class="tag success">VALID BY CONSTRUCTION</span>
          </div>
          <p class="card-desc">The final module merges the verified candidate for <code>@test</code> and falls back to the original for <code>@shift_mul</code>.</p>
        </div>
      `;

    } catch (e) {
      if (e instanceof BackendEngineError) {
         markFallback();
         errorMsg.innerHTML = '<strong>API Offline:</strong> ' + e.message;
      } else {
         errorMsg.innerHTML = '<strong>Error:</strong> ' + e.message;
      }
      errorMsg.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Assemble Final Module';
    }
  });
}
