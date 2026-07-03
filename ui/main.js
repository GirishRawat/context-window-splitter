import { initNav } from './nav.js';
import { detectBackend } from './backend.js';
import { initPhase1 } from './phase1.js';
import { initPhase2 } from './phase2.js';
import { initPhase5 } from './phase5.js';

function initTheme() {
  const toggleBtn = document.getElementById('theme-toggle');
  const moonIcon = document.getElementById('theme-icon-moon');
  const sunIcon = document.getElementById('theme-icon-sun');
  
  let currentTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', currentTheme);
  
  function updateIcons() {
    if (currentTheme === 'light') {
      sunIcon.classList.add('hidden');
      moonIcon.classList.remove('hidden');
    } else {
      moonIcon.classList.add('hidden');
      sunIcon.classList.remove('hidden');
    }
  }
  updateIcons();

  toggleBtn.addEventListener('click', () => {
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', currentTheme);
    localStorage.setItem('theme', currentTheme);
    updateIcons();
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
