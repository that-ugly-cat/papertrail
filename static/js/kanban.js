/*
 * Kanban drag-and-drop.
 *
 * Native HTML5 DnD, no library. The card is moved in the DOM optimistically and
 * reverted if the server refuses, so a failed move never leaves the board
 * showing something the database does not agree with.
 */
(function () {
  const board = document.getElementById('kanban');
  if (!board) return;
  const slug = board.dataset.slug;
  const canWrite = board.dataset.canwrite === '1';
  if (!canWrite) return;

  let dragged = null;
  let origin = null;      // column body we started from, for rollback
  let originNext = null;  // sibling we sat before, to restore exact position

  function cards() { return board.querySelectorAll('.pcard'); }
  function bodies() { return board.querySelectorAll('.col-body'); }

  function refreshCounts() {
    board.querySelectorAll('.col').forEach(col => {
      const n = col.querySelectorAll('.pcard').length;
      col.querySelector('.col-count').textContent = n;
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

    body.addEventListener('drop', e => {
      e.preventDefault();
      body.classList.remove('over');
      if (!dragged) return;
      const card = dragged;
      const from = origin, next = originNext;
      dragged = null;
      refreshCounts();

      const status = body.dataset.status;
      const order = [...body.querySelectorAll('.pcard')].map(c => c.dataset.id);

      fetch(`/api/w/${slug}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: card.dataset.id, status, order }),
      })
        .then(r => {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(data => {
          card.classList.add('saved');
          setTimeout(() => card.classList.remove('saved'), 700);
          /* The effective status can differ from the column we just dropped
             into (an open submission outranks the declared status), so redraw
             that line from the server's answer rather than guessing. */
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
        })
        .catch(() => {
          if (next) from.insertBefore(card, next);
          else from.appendChild(card);
          refreshCounts();
          card.classList.add('failed');
          setTimeout(() => card.classList.remove('failed'), 1200);
        });
    });
  });
})();
