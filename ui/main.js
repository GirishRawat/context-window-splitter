import { initNav } from './nav.js';
import { detectBackend } from './backend.js';
import { initPhase1 } from './phase1.js';
import { initPhase2 } from './phase2.js';
import { initPhase5 } from './phase5.js';

function initTheme() {
  const toggleBtn = document.getElementById('theme-toggle');
  
  let currentTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', currentTheme);
  
  function updateText() {
    if (currentTheme === 'light') {
      toggleBtn.textContent = 'Dark Mode';
    } else {
      toggleBtn.textContent = 'Light Mode';
    }
  }
  updateText();

  toggleBtn.addEventListener('click', () => {
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', currentTheme);
    localStorage.setItem('theme', currentTheme);
    updateText();
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  initNav();
  initPhase1();
  initPhase2();
  initPhase5();
  await detectBackend();
});
