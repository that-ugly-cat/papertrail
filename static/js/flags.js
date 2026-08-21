/*
 * The yellow dot.
 *
 * One click on a card, no dialog and no reload: the button flips immediately
 * and is put back if the server refuses, the same optimistic contract the
 * drag-and-drop in kanban.js works under. Nothing else on the card moves —
 * a flag is private and changes nothing anyone else can see, so there is no
 * derived state to re-render.
 *
 * The click is stopped before it reaches the card, because the card is
 * draggable and its title opens the project modal.
 */
(function () {
  const board = document.getElementById('kanban');
  if (!board) return;
  const boardSlug = board.dataset.slug;

  function paint(btn, on) {
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.closest('.pcard').classList.toggle('flagged', on);
  }

  board.addEventListener('click', async e => {
    const btn = e.target.closest('[data-flag]');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();

    const card = btn.closest('.pcard');
    const slug = card.dataset.slug || boardSlug;
    const was = btn.getAttribute('aria-pressed') === 'true';
    paint(btn, !was);
    btn.disabled = true;

    try {
      const r = await fetch(`/api/w/${slug}/p/${card.dataset.id}/flag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ flagged: !was }),
      });
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      paint(btn, !!data.flagged);      /* the row is the truth, not the button */
    } catch (err) {
      paint(btn, was);
    } finally {
      btn.disabled = false;
    }
  });

  /* Dragging a card by its dot is never what anyone means. */
  board.addEventListener('dragstart', e => {
    if (e.target.closest && e.target.closest('[data-flag]')) e.preventDefault();
  }, true);
})();
