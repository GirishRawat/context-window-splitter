import { initNav } from './nav.js';
import { detectBackend } from './backend.js';
import { initPhase1 } from './phase1.js';
import { initPhase2 } from './phase2.js';
import { initPhase5 } from './phase5.js';

document.addEventListener('DOMContentLoaded', async () => {
  initNav();
  initPhase1();
  initPhase2();
  initPhase5();
  await detectBackend();
});
