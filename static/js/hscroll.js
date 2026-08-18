/*
 * A horizontal scrollbar pinned to the bottom of the window.
 *
 * The kanban already scrolls sideways, but its own scrollbar sits at the bottom
 * of the *content*: with 49 cards in the Idea column that is far below the fold,
 * so reaching it means scrolling down first, and scrolling down loses sight of
 * the columns you were trying to reach. This mirrors it at the bottom of the
 * viewport instead.
 *
 * It is a proxy, not a replacement: an empty div as wide as the board's content
 * inside a fixed strip. Scrolling either one moves the other. It hides itself
 * when there is nothing to scroll, and when the board's own scrollbar is already
 * on screen, so it never doubles up.
 */
(function () {
  const board = document.getElementById('kanban');
  if (!board) return;

  const bar = document.createElement('div');
  bar.className = 'hscroll';
  const inner = document.createElement('div');
  bar.appendChild(inner);
  document.body.appendChild(bar);

  let syncing = false;

  function measure() {
    inner.style.width = board.scrollWidth + 'px';
    const overflows = board.scrollWidth > board.clientWidth + 1;
    // The board's own scrollbar is already visible when its bottom edge is
    // inside the window; showing a second one there would be noise.
    const own = board.getBoundingClientRect().bottom <= window.innerHeight;
    bar.style.display = overflows && !own ? 'block' : 'none';
    if (bar.style.display === 'block') bar.scrollLeft = board.scrollLeft;
  }

  function mirror(from, to) {
    if (syncing) return;
    syncing = true;
    to.scrollLeft = from.scrollLeft;
    syncing = false;
  }

  bar.addEventListener('scroll', () => mirror(bar, board));
  board.addEventListener('scroll', () => mirror(board, bar));
  window.addEventListener('scroll', measure, { passive: true });
  window.addEventListener('resize', measure);
  /* Columns change height when cards are dragged or filters applied. */
  new ResizeObserver(measure).observe(board);
  measure();
})();
