import { BACKEND_BASE, backendState, markFallback, BackendEngineError } from './backend.js';

// Ollama status state
let ollamaStatus = { running: false, models: [], error: null };

async function checkOllamaStatus() {
  const indicator = document.getElementById('ollama-status-indicator');
  const modelInfo = document.getElementById('ollama-model-info');
  
  if (!indicator) return;
  
  try {
    const res = await fetch(`${BACKEND_BASE}/api/ollama/status`);
    const data = await res.json();
    ollamaStatus = data;
    
    if (data.running && data.models.length > 0) {
      const modelNames = data.models.map(m => m.name).join(', ');
      indicator.innerHTML = `<span class="ollama-dot ollama-dot-ok"></span> Ollama Connected`;
      indicator.className = 'ollama-indicator ollama-ok';
      modelInfo.textContent = modelNames;
      modelInfo.classList.remove('hidden');
    } else if (data.running) {
      indicator.innerHTML = `<span class="ollama-dot ollama-dot-warn"></span> Ollama Running (no models pulled)`;
      indicator.className = 'ollama-indicator ollama-warn';
      modelInfo.textContent = 'Run: ollama pull qwen2.5-coder:3b';
      modelInfo.classList.remove('hidden');
    } else {
      indicator.innerHTML = `<span class="ollama-dot ollama-dot-off"></span> Ollama Offline`;
      indicator.className = 'ollama-indicator ollama-off';
      modelInfo.textContent = 'Start Ollama or enable mock mode';
      modelInfo.classList.remove('hidden');
    }
  } catch {
    // Backend itself is offline
    indicator.innerHTML = `<span class="ollama-dot ollama-dot-off"></span> Backend Offline`;
    indicator.className = 'ollama-indicator ollama-off';
    modelInfo.textContent = 'Start the Python API first';
    modelInfo.classList.remove('hidden');
  }
}

export function initPhase3() {
  const routeBtn = document.getElementById('route-btn');
  const irInput = document.getElementById('route-ir-input');
  const exampleBtn = document.getElementById('phase3-example-btn');
  const thresholdInput = document.getElementById('route-threshold-input');
  const thresholdValue = document.getElementById('route-threshold-value');
  const mockLlmCheckbox = document.getElementById('mock-llm-checkbox');
  const advancedToggle = document.getElementById('phase3-advanced-toggle');
  const advancedSection = document.getElementById('phase3-advanced-section');
  const errorMsg = document.getElementById('route-error-message');
  
  const functionsContainer = document.getElementById('route-functions-container');
  const emptyState = document.getElementById('route-empty-state');
  const summaryCard = document.getElementById('route-summary');
  const summaryFill = document.getElementById('route-summary-fill');
  const summaryText = document.getElementById('route-summary-text');

  if (!routeBtn) return;

  // Check Ollama status on load
  checkOllamaStatus();

  // Advanced section toggle
  if (advancedToggle && advancedSection) {
    advancedToggle.addEventListener('click', () => {
      advancedSection.classList.toggle('hidden');
      const icon = advancedToggle.querySelector('.toggle-icon');
      if (icon) icon.textContent = advancedSection.classList.contains('hidden') ? '▸' : '▾';
    });
  }

  thresholdInput.addEventListener('input', (e) => {
    thresholdValue.textContent = e.target.value;
  });

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

define i32 @max(i32 %a, i32 %b) {
entry:
  %cmp = icmp sgt i32 %a, %b
  br i1 %cmp, label %then, label %else
then:
  ret i32 %a
else:
  ret i32 %b
}

define i32 @use(i32 %x) {
entry:
  %t = call i32 @add(i32 %x, i32 1)
  %e = call i32 @external(i32 %t)
  ret i32 %e
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
}`,
    `; ModuleID = 'sample_math'
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i32 @shift_mul(i32 %a) {
entry:
  %mul = mul i32 %a, 4
  ret i32 %mul
}

define i32 @div_power_of_two(i32 %a) {
entry:
  %div = sdiv i32 %a, 8
  ret i32 %div
}`
  ];

  let currentExampleIdx = 0;
  exampleBtn.addEventListener('click', () => {
    currentExampleIdx = (currentExampleIdx + 1) % EXAMPLES.length;
    irInput.value = EXAMPLES[currentExampleIdx];
    clearOutput();
  });

  irInput.addEventListener('input', clearOutput);

  function clearOutput() {
    errorMsg.classList.add('hidden');
    emptyState.classList.remove('hidden');
    functionsContainer.innerHTML = '';
    summaryCard.classList.add('hidden');
    routeBtn.innerHTML = 'Route & Execute LLM';
    routeBtn.disabled = false;
  }

  function showError(msg) {
    errorMsg.textContent = msg;
    errorMsg.classList.remove('hidden');
    emptyState.classList.remove('hidden');
    functionsContainer.innerHTML = '';
    summaryCard.classList.add('hidden');
  }

  function renderFunctionCard(func) {
    const card = document.createElement('div');
    card.className = `glass-panel result-card function-card ${func.triaged_out ? 'triaged-card' : ''}`;

    let statusTag = func.triaged_out ? 'TRIAGED OUT' : 'ROUTED';
    let assignedModelBadge = func.assigned_model 
      ? `<span class="badge secondary" style="margin-left:auto;">${func.assigned_model}</span>` 
      : '';
      
    let codeBlock = '';
    if (func.llm_output) {
      codeBlock = `
        <div style="margin-top: 1rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
            <h4 style="font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); margin: 0;">LLM Output</h4>
            <div class="ir-toggle-container">
              <span class="toggle-label optimized-label active">Optimized</span>
              <label class="switch">
                <input type="checkbox" class="ir-toggle">
                <span class="slider"></span>
              </label>
              <span class="toggle-label original-label">Original</span>
            </div>
          </div>
          <pre class="ir-optimized-pre"><code class="language-llvm">${func.llm_output}</code></pre>
          <pre class="ir-original-pre hidden"><code class="language-llvm">${func.original_ir}</code></pre>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="card-header">
        <h3 style="display:flex; align-items:center; gap:0.5rem; width:100%;">
          Function: @<span class="fn-name"></span>
          ${assignedModelBadge}
        </h3>
        <span class="tag ${func.triaged_out ? '' : 'success'}">${statusTag}</span>
      </div>
      <p class="card-desc">${func.triaged_out
        ? 'Passed through unchanged due to low complexity.'
        : 'Optimized by the assigned LLM.'}</p>
        
      ${codeBlock}
    `;
    card.querySelector('.fn-name').textContent = func.name;

    // Add event listener for the toggle if it exists
    const toggle = card.querySelector('.ir-toggle');
    if (toggle) {
      const optimizedPre = card.querySelector('.ir-optimized-pre');
      const originalPre = card.querySelector('.ir-original-pre');
      const optimizedLabel = card.querySelector('.optimized-label');
      const originalLabel = card.querySelector('.original-label');
      
      toggle.addEventListener('change', (e) => {
        if (e.target.checked) {
          // Show Original
          optimizedPre.classList.add('hidden');
          originalPre.classList.remove('hidden');
          optimizedLabel.classList.remove('active');
          originalLabel.classList.add('active');
        } else {
          // Show Optimized
          originalPre.classList.add('hidden');
          optimizedPre.classList.remove('hidden');
          originalLabel.classList.remove('active');
          optimizedLabel.classList.add('active');
        }
      });
    }

    functionsContainer.appendChild(card);
  }

  function renderSummary(functions, threshold) {
    const total = functions.length;
    const triagedOut = functions.filter(f => f.triaged_out).length;
    const toOptimize = total - triagedOut;
    const pct = total > 0 ? (toOptimize / total) * 100 : 0;

    summaryFill.style.width = `${pct}%`;
    summaryText.innerHTML = `
      <strong>${total}</strong> function(s) processed &mdash;
      <span class="legend-dot legend-dot-accent"></span> ${toOptimize} routed to LLM &nbsp;
      <span class="legend-dot legend-dot-muted"></span> ${triagedOut} triaged out
    `;
    summaryCard.classList.remove('hidden');
  }

  routeBtn.addEventListener('click', async () => {
    const irText = irInput.value.trim();
    if (!irText) {
      showError('Please provide LLVM IR text.');
      return;
    }

    errorMsg.classList.add('hidden');
    emptyState.classList.add('hidden');
    functionsContainer.innerHTML = '';
    summaryCard.classList.add('hidden');

    const useMock = mockLlmCheckbox ? mockLlmCheckbox.checked : false;
    const originalText = routeBtn.innerHTML;
    routeBtn.innerHTML = useMock
      ? '<span class="spinner"></span> Routing (mock)...'
      : '<span class="spinner"></span> Routing via Ollama...';
    routeBtn.disabled = true;

    try {
      if (backendState === 'none') {
        throw new BackendEngineError();
      }

      const res = await fetch(`${BACKEND_BASE}/api/route`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ir_text: irText,
          complexity_threshold: parseInt(thresholdInput.value, 10),
          mock_llm: useMock
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Server error during routing');
      if (data.error) throw new Error(data.error);

      if (!data.functions || data.functions.length === 0) {
        showError('No functions found in the IR.');
        return;
      }

      data.functions.forEach(renderFunctionCard);
      renderSummary(data.functions, thresholdInput.value);

      // Refresh Ollama status after a successful route
      checkOllamaStatus();

    } catch (err) {
      if (err instanceof BackendEngineError) {
        markFallback('Phase 3 routing requires the Python backend.');
        showError('Backend offline. Please start the Python API.');
      } else {
        showError(err.message || 'An unknown error occurred.');
      }
    } finally {
      routeBtn.innerHTML = originalText;
      routeBtn.disabled = false;
    }
  });
}
