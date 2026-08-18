/*
 * Kanban drag-and-drop.
 *
 * Native HTML5 DnD, no library. The card moves in the DOM optimistically and is
 * put back if the server refuses, so a failed move never leaves the board
 * showing something the database does not agree with.
 *
 * Crossing the `submitted` boundary opens a dialog first: going in asks for the
 * venue, coming out asks what happened. That is the one moment the information
 * actually exists in someone's head — a form that asks later gets left empty.
 */
(function () {
  const board = document.getElementById('kanban');
  if (!board) return;
  const slug = board.dataset.slug;
  const canWrite = board.dataset.canwrite === '1';
  if (!canWrite) return;

  const dlg = document.getElementById('submitdlg');

  let dragged = null;
  let origin = null;      // column body we started from, for rollback
  let originNext = null;  // sibling we sat before, to restore exact position

  function cards() { return board.querySelectorAll('.pcard'); }
  function bodies() { return board.querySelectorAll('.col-body'); }

  function refreshCounts() {
    board.querySelectorAll('.col').forEach(col => {
      col.querySelector('.col-count').textContent =
        col.querySelectorAll('.pcard').length;
    });
  }

  /* Where should the dragged card land, given the pointer Y inside a column?
     Returns the element to insert before, or null for "append at the end". */
  function insertBefore(body, y) {
    const others = [...body.querySelectorAll('.pcard:not(.dragging)')];
    return others.find(card => {
      const box = card.getBoundingClientRect();
      return y < box.top + box.height / 2;
    }) || null;
  }

  /* Resolves to the extra fields for the move, or null if the user cancelled. */
  function askAboutSubmission(direction, title) {
    if (!dlg) return Promise.resolve({});
    const goingIn = direction === 'in';
    dlg.querySelector('#submitdlg-title').textContent =
      goingIn ? 'Sent out for review' : 'Back from review';
    dlg.querySelector('#submitdlg-sub').textContent = title;
    dlg.querySelector('#submitdlg-venue').style.display = goingIn ? '' : 'none';
    dlg.querySelector('#submitdlg-outcome').style.display = goingIn ? 'none' : '';
    dlg.querySelector('#submitdlg-note').value = '';
    if (goingIn) {
      dlg.querySelector('#submitdlg-venue-input').value = '';
      dlg.querySelector('#submitdlg-date').value =
        new Date().toISOString().slice(0, 10);
    }
    dlg.showModal();
    if (goingIn) dlg.querySelector('#submitdlg-venue-input').focus();

    return new Promise(resolve => {
      const ok = dlg.querySelector('#submitdlg-ok');
      const cancel = dlg.querySelector('#submitdlg-cancel');
      function done(value) {
        ok.removeEventListener('click', onOk);
        cancel.removeEventListener('click', onCancel);
        dlg.removeEventListener('cancel', onCancel);
        dlg.close();
        resolve(value);
      }
      function onOk() {
        done(goingIn
          ? { venue: dlg.querySelector('#submitdlg-venue-input').value,
              submitted_at: dlg.querySelector('#submitdlg-date').value,
              note: dlg.querySelector('#submitdlg-note').value }
          : { outcome: dlg.querySelector('#submitdlg-outcome-select').value,
              note: dlg.querySelector('#submitdlg-note').value });
      }
      function onCancel(e) { if (e) e.preventDefault(); done(null); }
      ok.addEventListener('click', onOk);
      cancel.addEventListener('click', onCancel);
      dlg.addEventListener('cancel', onCancel);   /* Esc key */
    });
  }

  cards().forEach(bindCard);

  function bindCard(card) {
    card.addEventListener('dragstart', e => {
      dragged = card;
      origin = card.parentElement;
      originNext = card.nextElementSibling;
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      /* Firefox needs data set for the drag to start at all. */
      e.dataTransfer.setData('text/plain', card.dataset.id);
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      bodies().forEach(b => b.classList.remove('over'));
    });
  }

  bodies().forEach(body => {
    body.addEventListener('dragover', e => {
      if (!dragged) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      body.classList.add('over');
      const ref = insertBefore(body, e.clientY);
      if (ref) body.insertBefore(dragged, ref);
      else body.appendChild(dragged);
    });

    body.addEventListener('dragleave', e => {
      if (!body.contains(e.relatedTarget)) body.classList.remove('over');
    });

    body.addEventListener('drop', async e => {
      e.preventDefault();
      body.classList.remove('over');
      if (!dragged) return;
      const card = dragged;
      const from = origin, next = originNext;
      const fromStatus = from.dataset.status;
      const status = body.dataset.status;
      dragged = null;
      refreshCounts();

      function rollback(mark) {
        if (next) from.insertBefore(card, next);
        else from.appendChild(card);
        refreshCounts();
        if (mark) {
          card.classList.add('failed');
          setTimeout(() => card.classList.remove('failed'), 1200);
        }
      }

      let extra = {};
      if (status !== fromStatus &&
          (status === 'submitted' || fromStatus === 'submitted')) {
        extra = await askAboutSubmission(
          status === 'submitted' ? 'in' : 'out',
          card.querySelector('.pcard-title').textContent.trim());
        if (extra === null) { rollback(false); return; }   /* cancelled */
      }

      const order = [...body.querySelectorAll('.pcard')].map(c => c.dataset.id);

      try {
        const r = await fetch(`/api/w/${slug}/move`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            Object.assign({ project_id: card.dataset.id, status, order }, extra)),
        });
        if (!r.ok) throw new Error(r.status);
        const data = await r.json();
        card.classList.add('saved');
        setTimeout(() => card.classList.remove('saved'), 700);
        /* The effective status can differ from the column just dropped into —
           an open submission outranks the declared status — so redraw that line
           from the server's answer rather than guessing. */
        const eff = data.effective || {};
        let line = card.querySelector('.pcard-eff');
        if (eff.detail) {
          if (!line) {
            line = document.createElement('div');
            line.className = 'pcard-eff';
            card.querySelector('.pcard-title').after(line);
          }
          line.textContent = `${eff.label} · ${eff.detail}`;
        } else if (line) {
          line.remove();
        }
      } catch (err) {
        rollback(true);
      }
    });
  });
})();
