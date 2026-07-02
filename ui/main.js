document.addEventListener('DOMContentLoaded', () => {
  const parseBtn = document.getElementById('parse-btn');
  const irInput = document.getElementById('ir-input');
  const errorMsg = document.getElementById('error-message');
  const emptyState = document.getElementById('empty-state');
  
  const preambleContainer = document.getElementById('preamble-container');
  const preambleOutput = document.getElementById('preamble-output');
  const functionsContainer = document.getElementById('functions-container');

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

    try {
      // We assume FastAPI runs on port 8000 locally
      const response = await fetch('http://localhost:8000/api/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ir_text: irText })
      });

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
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
          card.style.animationDelay = `${(index + 1) * 0.1}s`;
          
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
      parseBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg> Parse & Extract`;
      parseBtn.disabled = false;
    }
  });
});
