// ---------------------------------------------------------------------------
// Phase 2 view — Triage & Profiling
//
// Mirrors llmcompile/phases/p2_triage.py: cyclomatic complexity (decision
// points + 1) and a token count drive a triage decision (below-threshold
// functions are skipped) and a Phase 3 routing tier preview.
// ---------------------------------------------------------------------------

import { parseModuleJS } from './llvmir.js';
import { BACKEND_BASE, backendState, markFallback, BackendEngineError } from './backend.js';

// Mirrors TriageConfig.token_tier_boundaries in llmcompile/config.py
const TOKEN_TIERS = [
  { key: 'fast', label: 'Fast / Local', min: 0, max: 8000 },
  { key: 'mid', label: 'Mid Tier', min: 8000, max: 32000 },
  { key: 'frontier', label: 'Frontier', min: 32000, max: Infinity },
];

function predictTier(tokenCount) {
  return TOKEN_TIERS.find(t => tokenCount >= t.min && tokenCount < t.max) || TOKEN_TIERS[TOKEN_TIERS.length - 1];
}

// JS fallback complexity calculation — mirrors _cyclomatic_complexity_from_text
function cyclomaticComplexityJS(irText) {
  const conditionalBranches = (irText.match(/\bbr\s+i1\s+%\w+,/g) || []).length;
  const switches = (irText.match(/\bswitch\s+/g) || []).length;
  const selects = (irText.match(/\bselect\s+i1\s+/g) || []).length;
  const decisionPoints = conditionalBranches + switches + selects;
  return Math.max(1, decisionPoints + 1);
}

// JS fallback token estimate — tiktoken isn't available client-side, so we use
// the ~2 chars/token ratio for LLVM IR cited in Cummins et al. (see README §11).
function estimateTokensJS(text) {
  return Math.max(1, Math.ceil(text.trim().length / 2));
}

function triageModuleJS(irText, threshold) {
  const { preamble, functions } = parseModuleJS(irText);
  const triaged = functions.map(fn => {
    const complexity = cyclomaticComplexityJS(fn.original_ir);
    const token_count = estimateTokensJS(fn.original_ir);
    return {
      name: fn.name,
      original_ir: fn.original_ir,
      complexity,
      token_count,
      triaged_out: complexity < threshold,
    };
  });
  return { preamble, functions: triaged, threshold };
}

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

export function initPhase2() {
  const triageBtn = document.getElementById('triage-btn');
  const irInput = document.getElementById('triage-ir-input');
  const errorMsg = document.getElementById('triage-error-message');
  const emptyState = document.getElementById('triage-empty-state');
  const exampleBtn = document.getElementById('phase2-example-btn');

  let currentIdx = 0;
  exampleBtn.addEventListener('click', () => {
    currentIdx = (currentIdx + 1) % EXAMPLES.length;
    irInput.value = EXAMPLES[currentIdx];
  });
  const thresholdInput = document.getElementById('threshold-input');
  const thresholdValue = document.getElementById('threshold-value');

  const summaryCard = document.getElementById('triage-summary');
  const summaryFill = document.getElementById('triage-summary-fill');
  const summaryText = document.getElementById('triage-summary-text');
  const functionsContainer = document.getElementById('triage-functions-container');

  thresholdInput.addEventListener('input', () => {
    thresholdValue.textContent = thresholdInput.value;
  });

  function renderCard(func, index, threshold) {
    const tier = predictTier(func.token_count);
    const scale = Math.max(10, threshold * 2);
    const meterPct = Math.min(100, (func.complexity / scale) * 100);
    const thresholdPct = Math.min(100, (threshold / scale) * 100);

    const card = document.createElement('div');
    card.className = 'glass-panel result-card triage-card';
    card.style.animationDelay = `${(index + 1) * 0.05}s`;

    // Triaged-out functions skip Phase 3 entirely, so they are never routed to
    // a model tier — show that instead of a (misleading) routing tier tag.
    const routingTag = func.triaged_out
      ? `<span class="tag">skips routing</span>`
      : `<span class="tag tier-${tier.key}">${tier.label} routing</span>`;

    // Static markup only. The function name is set via textContent below so a
    // quoted IR name containing '<'/'>' renders literally and can't inject.
    card.innerHTML = `
      <div class="card-header">
        <h3>
          
          Function: @<span class="fn-name"></span>
        </h3>
        <span class="tag ${func.triaged_out ? '' : 'success'}">${func.triaged_out ? 'TRIAGED OUT' : 'TO OPTIMIZE'}</span>
      </div>
      <p class="card-desc">${func.triaged_out
        ? 'Below the complexity threshold — passes through to Phase 6 unchanged, skipping the LLM/verification phases.'
        : 'Above the complexity threshold — routed to Phase 3 for LLM-driven optimization.'}</p>

      <div class="metrics-row">
        <div class="metric">
          <div class="metric-label-row">
            <span class="metric-label">Cyclomatic Complexity</span>
            <span class="metric-value">${func.complexity}</span>
          </div>
          <div class="meter">
            <div class="meter-fill ${func.triaged_out ? 'meter-fill-muted' : ''}" style="width: ${meterPct}%"></div>
            <div class="meter-threshold" style="left: ${thresholdPct}%" title="Threshold: ${threshold}"></div>
          </div>
        </div>

        <div class="metric">
          <div class="metric-label-row">
            <span class="metric-label">Token Count</span>
            <span class="metric-value">${func.token_count.toLocaleString()}</span>
          </div>
          ${routingTag}
        </div>
      </div>
    `;
    card.querySelector('.fn-name').textContent = func.name;
    functionsContainer.appendChild(card);
  }

  function renderSummary(functions, threshold) {
    const total = functions.length;
    const triagedOut = functions.filter(f => f.triaged_out).length;
    const toOptimize = total - triagedOut;
    const pct = total > 0 ? (toOptimize / total) * 100 : 0;

    summaryFill.style.width = `${pct}%`;
    summaryText.innerHTML = `
      <strong>${total}</strong> function(s) analyzed at threshold <strong>${threshold}</strong> &mdash;
      <span class="legend-dot legend-dot-accent"></span> ${toOptimize} to optimize &nbsp;
      <span class="legend-dot legend-dot-muted"></span> ${triagedOut} triaged out
    `;
    summaryCard.classList.remove('hidden');
  }

  triageBtn.addEventListener('click', async () => {
    const irText = irInput.value;
    if (!irText.trim()) return;
    const threshold = parseInt(thresholdInput.value, 10) || 5;

    triageBtn.innerHTML = ` Analyzing...`;
    triageBtn.disabled = true;
    errorMsg.classList.add('hidden');
    emptyState.classList.add('hidden');
    summaryCard.classList.add('hidden');
    functionsContainer.innerHTML = '';

    let data;

    try {
      if (backendState.available) {
        try {
          const response = await fetch(`${BACKEND_BASE}/api/triage`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ir_text: irText, complexity_threshold: threshold })
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
          console.warn("Backend unavailable, falling back to JS:", fetchErr);
          data = triageModuleJS(irText, threshold);
          markFallback();
        }
      } else {
        data = triageModuleJS(irText, threshold);
      }

      if (data.functions && data.functions.length > 0) {
        renderSummary(data.functions, data.threshold ?? threshold);
        data.functions.forEach((func, index) => renderCard(func, index, data.threshold ?? threshold));
      } else {
        emptyState.classList.remove('hidden');
        emptyState.innerHTML = '<p>No function definitions found.</p>';
      }

    } catch (err) {
      errorMsg.textContent = err.message;
      errorMsg.classList.remove('hidden');
      emptyState.classList.remove('hidden');
    } finally {
      triageBtn.innerHTML = ` Analyze & Triage`;
      triageBtn.disabled = false;
    }
  });
}
