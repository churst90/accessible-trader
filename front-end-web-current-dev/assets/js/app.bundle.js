// assets/js/app.bundle.js
/**
 * Global theme toggle.
 */
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const apply = theme => {
    document.documentElement.setAttribute('data-theme', theme);
    btn.setAttribute('aria-pressed', theme === 'dark');
    btn.textContent = theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
  };
  let theme = localStorage.getItem('theme') || 'light';
  apply(theme);
  btn.addEventListener('click', () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', theme);
    apply(theme);
  });
});
