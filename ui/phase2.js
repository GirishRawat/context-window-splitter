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

export function initPhase2() {
  const triageBtn = document.getElementById('triage-btn');
  const irInput = document.getElementById('triage-ir-input');
  const errorMsg = document.getElementById('triage-error-message');
  const emptyState = document.getElementById('triage-empty-state');
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

    card.innerHTML = `
      <div class="card-header">
        <h3>
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
          Function: @${func.name}
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
          <span class="tag tier-${tier.key}">${tier.label} routing</span>
        </div>
      </div>
    `;
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

    triageBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-2" style="animation: spin 1s linear infinite;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Analyzing...`;
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
      triageBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg> Analyze & Triage`;
      triageBtn.disabled = false;
    }
  });
}
