// ---------------------------------------------------------------------------
// Phase tab navigation — switches between the Phase 1 and Phase 2 views and
// keeps the choice in the URL hash so it survives a reload/share.
// ---------------------------------------------------------------------------

export function initNav() {
  const tabs = Array.from(document.querySelectorAll('.phase-tab'));
  const views = Array.from(document.querySelectorAll('.view'));

  function activate(view) {
    tabs.forEach(tab => tab.classList.toggle('active', tab.dataset.view === view));
    views.forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
  }

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const view = tab.dataset.view;
      window.location.hash = view;
      activate(view);
    });
  });

  const initial = window.location.hash.replace('#', '');
  activate(tabs.some(t => t.dataset.view === initial) ? initial : 'overview');
}
