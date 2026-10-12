// Progressive enhancement: all routes and forms also work without JavaScript.
document.querySelectorAll('[data-password-toggle]').forEach((button) => {
  button.hidden = false;
  button.addEventListener('click', () => {
    const input = document.getElementById(button.getAttribute('aria-controls'));
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.textContent = visible ? 'Hide' : 'Show';
    button.setAttribute('aria-pressed', String(visible));
  });
});

document.querySelectorAll('form[data-pending]').forEach((form) => {
  form.addEventListener('submit', () => {
    form.setAttribute('aria-busy', 'true');
    const button = form.querySelector('button[type="submit"]');
    button.dataset.originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = form.dataset.pending;
  });
});

document.querySelectorAll('form[data-shortcut] textarea').forEach((input) => {
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      input.form.requestSubmit();
    }
  });
});

document.querySelectorAll('a[href="/#compose"]').forEach((link) => {
  link.addEventListener('click', () => {
    if (location.pathname === '/') document.getElementById('post-body')?.focus();
  });
});

window.addEventListener('pageshow', () => {
  document.querySelectorAll('form[aria-busy="true"]').forEach((form) => {
    form.removeAttribute('aria-busy');
    const button = form.querySelector('button[type="submit"]');
    button.disabled = false;
    button.textContent = button.dataset.originalLabel;
  });
});
