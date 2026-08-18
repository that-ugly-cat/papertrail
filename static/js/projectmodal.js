/*
 * Open a project card in a dialog, without giving up its URL.
 *
 * The card is still /w/<slug>/p/<id>: clicking pushes that URL, the back button
 * closes the dialog, and hitting the address directly (a shared link, a reload)
 * serves the full page as before. The dialog just fetches the same template
 * with ?partial=1.
 *
 * Forms inside the dialog are intercepted so a save does not navigate away from
 * the board. Anything that wrote is remembered, and the board reloads on close —
 * a status change from inside the dialog has to move the card, and re-deriving
 * that in JS would mean duplicating effective_status() in a second language.
 */
(function () {
  const board = document.getElementById('kanban');
  const dlg = document.getElementById('projdlg');
  if (!dlg) return;

  const body = dlg.querySelector('#projdlg-body');
  const boardUrl = location.pathname + location.search;
  let dirty = false;

  function open(url, push) {
    return fetch(url + (url.includes('?') ? '&' : '?') + 'partial=1',
                 { headers: { 'Accept': 'text/html' } })
      .then(r => {
        if (!r.ok) throw new Error(r.status);
        return r.text();
      })
      .then(html => {
        body.innerHTML = html;
        bindForms();
        /* innerHTML never runs <script>, so anything the card needs has to be
           re-armed from here. */
        if (window.PT_initNotes) window.PT_initNotes(body);
        if (!dlg.open) dlg.showModal();
        body.scrollTop = 0;
        if (push) history.pushState({ project: url }, '', url);
      })
      .catch(() => { location.href = url; });   /* fall back to the real page */
  }

  function close(pop) {
    if (dlg.open) dlg.close();
    if (dirty) { location.href = boardUrl; return; }
    if (!pop) history.pushState({}, '', boardUrl);
  }

  /* Submit in place, then redraw the dialog from the server's new state. */
  function bindForms() {
    body.querySelectorAll('form').forEach(form => {
      form.addEventListener('submit', e => {
        e.preventDefault();
        const url = history.state && history.state.project
          ? history.state.project : location.pathname;
        fetch(form.action, { method: 'POST', body: new FormData(form) })
          .then(r => {
            if (!r.ok) throw new Error(r.status);
            dirty = true;
            /* Most forms redirect back to the project and the dialog redraws.
               Some do not: deleting sends you to the board, because the thing
               the dialog was showing no longer exists. Follow wherever the
               server actually landed instead of assuming it stayed put. */
            const landed = new URL(r.url, location.href).pathname;
            if (!landed.startsWith(url.split('?')[0])) {
              location.href = r.url;
              return;
            }
            return open(url, false);
          })
          .catch(() => { form.submit(); });   /* let the browser do it instead */
      });
    });
  }

  if (board) {
    board.addEventListener('click', e => {
      const link = e.target.closest('.pcard-title');
      if (!link || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      open(link.getAttribute('href'), true);
    });
  }

  dlg.querySelector('#projdlg-close').addEventListener('click', () => close(false));
  dlg.addEventListener('cancel', e => { e.preventDefault(); close(false); });
  /* Clicking the backdrop (outside the panel) closes too. */
  dlg.addEventListener('click', e => { if (e.target === dlg) close(false); });

  window.addEventListener('popstate', e => {
    if (e.state && e.state.project) open(e.state.project, false);
    else close(true);
  });
})();
