// ---------------------------------------------------------------------------
// Pure JavaScript Parser Fallback (For GitHub Pages / Static hosting)
// Matches the exact text-splitting and declaration derivation logic of p1_parse.py
// ---------------------------------------------------------------------------

function functionName(line) {
  const match = line.match(/@(?:"([^"]*)"|([\w.$\-]+))\s*\(/);
  if (!match) {
    throw new Error(`Could not parse function name from: ${line}`);
  }
  return match[1] !== undefined ? match[1] : match[2];
}

function signatureToDeclaration(signatureLine) {
  let sig = signatureLine.trim();
  if (sig.endsWith("{")) {
    sig = sig.slice(0, -1).trimEnd();
  }

  // Remove metadata attachments: ' !dbg !12'
  sig = sig.replace(/\s+!\w+\s+!\d+/g, "");

  const definitionOnlyClauses = [
    " personality ",
    " prologue ",
    " prefix ",
    " gc ",
    " section ",
    " comdat"
  ];

  let earliest = sig.length;
  for (const clause of definitionOnlyClauses) {
    const idx = sig.indexOf(clause);
    if (idx !== -1) {
      earliest = Math.min(earliest, idx);
    }
  }
  sig = sig.slice(0, earliest).trimEnd();

  if (!sig.startsWith("define")) {
    throw new Error(`Expected a \`define\` signature, got: ${signatureLine}`);
  }
  return "declare" + sig.slice("define".length);
}

function splitModuleText(irText) {
  const lines = irText.split(/\r?\n/);
  const preambleLines = [];
  const blocks = [];

  let i = 0;
  const n = lines.length;
  while (i < n) {
    const line = lines[i];
    if (line.trimStart().startsWith("define ")) {
      const signature = line;
      const body = [line];
      i++;
      let closed = false;
      while (i < n) {
        body.push(lines[i]);
        if (lines[i].trimEnd() === "}") {
          closed = true;
          break;
        }
        i++;
      }
      if (!closed) {
        throw new Error(`Unterminated function body starting at: ${signature.trim()}`);
      }
      blocks.push({
        name: functionName(signature),
        signature: signature,
        text: body.join("\n")
      });
      i++;
    } else {
      preambleLines.push(line);
      i++;
    }
  }
  return { preambleLines, blocks };
}

function parseModuleJS(irText) {
  const { preambleLines, blocks } = splitModuleText(irText);
  const basePreamble = preambleLines.join("\n").trim();
  
  const declarations = {};
  for (const block of blocks) {
    declarations[block.name] = signatureToDeclaration(block.signature);
  }

  const functions = [];
  for (const block of blocks) {
    const name = block.name;
    const otherDecls = Object.entries(declarations)
      .filter(([fnName]) => fnName !== name)
      .map(([, decl]) => decl);

    const parts = [basePreamble];
    if (otherDecls.length > 0) {
      parts.push("; --- declarations of sibling functions ---");
      parts.push(...otherDecls);
    }
    parts.push("");
    parts.push(block.text);
    const standaloneIr = parts.filter(p => p !== null).join("\n").trim() + "\n";
    functions.push({ name, original_ir: standaloneIr });
  }

  return { preamble: basePreamble, functions };
}

// ---------------------------------------------------------------------------
// Main UI Logic & Engine Auto-Detection
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
  const parseBtn = document.getElementById('parse-btn');
  const irInput = document.getElementById('ir-input');
  const errorMsg = document.getElementById('error-message');
  const emptyState = document.getElementById('empty-state');
  const engineBadge = document.getElementById('engine-badge');
  
  const preambleContainer = document.getElementById('preamble-container');
  const preambleOutput = document.getElementById('preamble-output');
  const functionsContainer = document.getElementById('functions-container');

  const BACKEND_URL = 'http://localhost:8000/api/parse';
  let isBackendAvailable = false;

  // Detect if Python Backend is available
  async function checkBackend() {
    try {
      // Use an empty or simple payload to check connection
      const response = await fetch(BACKEND_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ir_text: '; check connection' })
      });
      if (response.ok) {
        isBackendAvailable = true;
        engineBadge.textContent = 'Python Backend (Strict LLVM)';
        engineBadge.className = 'badge python';
      } else {
        throw new Error();
      }
    } catch {
      isBackendAvailable = false;
      engineBadge.textContent = 'JS Fallback Engine (Static Site)';
      engineBadge.className = 'badge js';
    }
  }

  // Run detection on load
  await checkBackend();

  parseBtn.addEventListener('click', async () => {
    const irText = irInput.value;
    if (!irText.trim()) return;

    // UI Feedback
    parseBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-loader-2" style="animation: spin 1s linear infinite;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Parsing...`;
    parseBtn.disabled = true;
    errorMsg.classList.add('hidden');
    emptyState.classList.add('hidden');
    
    // Clear old outputs
    preambleContainer.classList.add('hidden');
    functionsContainer.innerHTML = '';

    let data;

    try {
      if (isBackendAvailable) {
        // Attempt to parse via local FastAPI
        try {
          const response = await fetch(BACKEND_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ir_text: irText })
          });
          data = await response.json();
          if (data.error) {
            throw new Error(data.error);
          }
        } catch (fetchErr) {
          // If fetch fails mid-flight, fallback to JS
          console.warn("Backend failed mid-flight, falling back to JS:", fetchErr);
          data = parseModuleJS(irText);
          // Briefly update badge to reflect mid-flight fallback
          engineBadge.textContent = 'JS Fallback Engine (Static Site)';
          engineBadge.className = 'badge js';
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
          
          card.innerHTML = `
            <div class="card-header">
              <h3>
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                Function: @${func.name}
              </h3>
              <span class="tag success">Independently Assemblable</span>
            </div>
            <p class="card-desc">Standalone IR snippet carrying necessary sibling declarations and full function body.</p>
            <pre><code class="language-llvm">${func.original_ir}</code></pre>
          `;
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
      parseBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-zap"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Parse & Extract`;
      parseBtn.disabled = false;
    }
  });
});
