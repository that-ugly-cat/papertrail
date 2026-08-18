/*
 * Notes: a full-size editor for writing, and a clamp for reading.
 *
 * Two things this has to survive. The project card is also rendered inside a
 * dialog on the board, injected with innerHTML — so a <script> inside the
 * partial would never run, and this has to be callable again after each
 * injection. And it must be idempotent, because it is called again on every
 * redraw: marking what it has already handled is cheaper than unbinding.
 */
(function () {
  function initNotes(root) {
    root = root || document;

    /* Write: the mini box stays for one-liners, the dialog is for real notes. */
    root.querySelectorAll('[data-note-expand]').forEach(btn => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => {
        const dlg = root.querySelector('#notedlg');
        if (!dlg) return;
        /* Carry over whatever was already typed, so clicking "bigger" mid
           sentence does not throw the sentence away. */
        const small = btn.closest('form').querySelector('textarea');
        const big = dlg.querySelector('textarea');
        if (small && big && small.value.trim() && !big.value.trim()) {
          big.value = small.value;
        }
        dlg.showModal();
        if (big) big.focus();
      });
    });

    root.querySelectorAll('[data-note-close]').forEach(btn => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => {
        const dlg = btn.closest('dialog');
        if (dlg) dlg.close();
      });
    });

    /* Read: clamp only what actually overflows. Measuring beats guessing at a
       character count, because three lines of a table and three lines of prose
       are very different amounts of text. */
    root.querySelectorAll('.note-body.clamp').forEach(el => {
      if (el.dataset.clamped) return;
      el.dataset.clamped = '1';
      if (el.scrollHeight - el.clientHeight < 4) {
        el.classList.remove('clamp');       /* short enough: nothing to hide */
        return;
      }
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'linkbtn note-more';
      more.textContent = 'Show more';
      more.addEventListener('click', () => {
        const open = el.classList.toggle('clamp');
        more.textContent = open ? 'Show more' : 'Show less';
      });
      el.after(more);
    });
  }

  window.PT_initNotes = initNotes;
  document.addEventListener('DOMContentLoaded', () => initNotes(document));
})();
