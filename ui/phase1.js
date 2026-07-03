// ---------------------------------------------------------------------------
// Phase 1 view — Parse & Extract
// ---------------------------------------------------------------------------

import { parseModuleJS } from './llvmir.js';
import { BACKEND_BASE, backendState, markFallback, BackendEngineError } from './backend.js';

const EXAMPLES = [
  `; ModuleID = 'sample'
source_filename = "sample.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

@counter = global i32 0, align 4

declare i32 @external(i32)

define i32 @add(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}

define i32 @use(i32 %x) {
entry:
  %t = call i32 @add(i32 %x, i32 1)
  %e = call i32 @external(i32 %t)
  ret i32 %e
}`,
  `; ModuleID = 'sample_max'
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @max(i32 %a, i32 %b) {
entry:
  %cmp = icmp sgt i32 %a, %b
  br i1 %cmp, label %then, label %else
then:
  ret i32 %a
else:
  ret i32 %b
}`,
  `; ModuleID = 'sample_loop'
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @sum(i32 %n) {
entry:
  br label %loop
loop:
  %i = phi i32 [ 0, %entry ], [ %i.next, %loop ]
  %s = phi i32 [ 0, %entry ], [ %s.next, %loop ]
  %i.next = add i32 %i, 1
  %s.next = add i32 %s, %i
  %cmp = icmp slt i32 %i.next, %n
  br i1 %cmp, label %loop, label %exit
exit:
  ret i32 %s.next
}`
];

export function initPhase1() {
  const parseBtn = document.getElementById('parse-btn');
  const irInput = document.getElementById('ir-input');
  const errorMsg = document.getElementById('error-message');
  const emptyState = document.getElementById('empty-state');
  const exampleBtn = document.getElementById('phase1-example-btn');

  let currentIdx = 0;
  exampleBtn.addEventListener('click', () => {
    currentIdx = (currentIdx + 1) % EXAMPLES.length;
    irInput.value = EXAMPLES[currentIdx];
  });

  const preambleContainer = document.getElementById('preamble-container');
  const preambleOutput = document.getElementById('preamble-output');
  const functionsContainer = document.getElementById('functions-container');

  parseBtn.addEventListener('click', async () => {
    const irText = irInput.value;
    if (!irText.trim()) return;

    // UI Feedback
    parseBtn.innerHTML = ` Parsing...`;
    parseBtn.disabled = true;
    errorMsg.classList.add('hidden');
    emptyState.classList.add('hidden');

    // Clear old outputs
    preambleContainer.classList.add('hidden');
    functionsContainer.innerHTML = '';

    let data;

    try {
      if (backendState.available) {
        // Attempt to parse via local FastAPI
        try {
          const response = await fetch(`${BACKEND_BASE}/api/parse`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ir_text: irText })
          });
          if (!response.ok) {
            throw new Error(`Backend returned ${response.status}`);
          }
          data = await response.json();
          if (data.error) {
            // A real parse error from the engine should surface to the user,
            // not silently fall back to the (more lenient) JS engine.
            throw new BackendEngineError(data.error);
          }
        } catch (fetchErr) {
          if (fetchErr instanceof BackendEngineError) throw fetchErr;
          // If fetch fails at the transport level, fall back to JS
          console.warn("Backend unavailable, falling back to JS:", fetchErr);
          data = parseModuleJS(irText);
          markFallback();
        }
      } else {
        // Use pure JS engine directly
        data = parseModuleJS(irText);
      }

      // Render Preamble
      if (data.preamble) {
        preambleOutput.textContent = data.preamble;
        preambleContainer.classList.remove('hidden');
      }

      // Render Functions
      if (data.functions && data.functions.length > 0) {
        data.functions.forEach((func, index) => {
          const card = document.createElement('div');
          card.className = 'glass-panel result-card';
          card.style.animationDelay = `${(index + 1) * 0.05}s`;

          // Static markup only. Function name and IR body are set via
          // textContent below so IR containing '<'/'>' (e.g. `<vscale x 4 x i32>`)
          // or pasted markup renders literally and cannot inject into the DOM.
          card.innerHTML = `
            <div class="card-header">
              <h3>
                
                Function: @<span class="fn-name"></span>
              </h3>
              <span class="tag success">Independently Assemblable</span>
            </div>
            <p class="card-desc">Standalone IR snippet carrying necessary sibling declarations and full function body.</p>
            <pre><code class="language-llvm"></code></pre>
          `;
          card.querySelector('.fn-name').textContent = func.name;
          card.querySelector('code').textContent = func.original_ir;
          functionsContainer.appendChild(card);
        });
      } else {
        emptyState.classList.remove('hidden');
        emptyState.innerHTML = '<p>No function definitions found.</p>';
      }

    } catch (err) {
      errorMsg.textContent = err.message;
      errorMsg.classList.remove('hidden');
      emptyState.classList.remove('hidden');
    } finally {
      // Reset Button
      parseBtn.innerHTML = ` Parse & Extract`;
      parseBtn.disabled = false;
    }
  });
}
