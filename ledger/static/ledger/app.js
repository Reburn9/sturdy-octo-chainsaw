const toggle = document.querySelector('.menu-toggle');
toggle?.addEventListener('click', () => {
  const open = document.body.classList.toggle('nav-open');
  toggle.setAttribute('aria-expanded', String(open));
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    document.body.classList.remove('nav-open');
    toggle?.setAttribute('aria-expanded', 'false');
  }
});
document.querySelectorAll('[data-submit-form]').forEach(form => {
  form.addEventListener('submit', event => {
    if (form.dataset.submitting) {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    // Keep the clicked submit button enabled so its action reaches the server.
    form.setAttribute('aria-busy', 'true');
  });
});
