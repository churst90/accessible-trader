<?php
// Ensure session is started so we can read login state
if (session_status() === PHP_SESSION_NONE) {
    session_start();
}

$userLoggedIn = !empty($_SESSION['logged_in']) && $_SESSION['logged_in'] === true;
$username     = $_SESSION['username'] ?? '';
?><!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Accessible Trader</title>

  <!-- Set initial theme from localStorage -->
  <script>
    (function(){
      try {
        const theme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', theme);
      } catch(e) {
        console.warn('Could not load theme preference', e);
      }
    })();
  </script>

  <link rel="stylesheet" href="/assets/css/base.css">
  <link rel="stylesheet" href="/assets/css/light-theme.css">
  <link rel="stylesheet" href="/assets/css/dark-theme.css">
</head>
<body>
  <header role="banner">
    <div class="site-header">
      <h1><a href="/" style="color: var(--text-color)">Accessible Trader</a></h1>
      <nav role="navigation" aria-label="Main">
        <ul>
          <li><a href="/">Home</a></li>
          <li><a href="/chart">Chart</a></li>
          <li><a href="/faq">FAQ</a></li>
          <li><a href="/support">Support</a></li>
          <?php if ($userLoggedIn): ?>
            <li><a href="/profile">Profile (<?= htmlspecialchars($username) ?>)</a></li>
            <li><a href="/logout">Logout</a></li>
          <?php else: ?>
            <li><a href="/register">Register</a></li>
            <li><a href="/login">Login</a></li>
          <?php endif; ?>
        </ul>
      </nav>

      <!-- Theme toggle -->
      <button
        id="theme-toggle"
        aria-label="Toggle light/dark mode"
        aria-pressed="false"
        style="margin-left:auto; padding:0.5rem; border:1px solid var(--border-color); background:var(--background-color); color:var(--text-color); border-radius:4px;"
      >Toggle Theme</button>
    </div>
  </header>

  <main id="main">

  <!-- Theme toggle script -->
  <script>
    document.addEventListener('DOMContentLoaded', function(){
      const btn = document.getElementById('theme-toggle');
      if (!btn) return;

      function updateButton(theme) {
        const isDark = theme === 'dark';
        btn.setAttribute('aria-pressed', isDark);
        btn.textContent = isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode';
      }

      // Initialize button state
      const current = document.documentElement.getAttribute('data-theme') || 'light';
      updateButton(current);

      btn.addEventListener('click', function(){
        const newTheme = (document.documentElement.getAttribute('data-theme') === 'dark') ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        try { localStorage.setItem('theme', newTheme); } catch {}
        updateButton(newTheme);
      });
    });
  </script>
