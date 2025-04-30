<?php
// src/Views/auth/login.php
?>
<section>
    <h1>Login</h1>

    <?php if (!empty($error)): ?>
        <p role="alert" style="color: red;"><?= htmlspecialchars($error) ?></p>
    <?php endif; ?>

    <form action="/login/submit" method="POST">
        <div>
            <label for="username">Username</label><br>
            <input
                type="text"
                id="username"
                name="username"
                required
                value="<?= htmlspecialchars($username ?? '') ?>"
            >
        </div>
        <div>
            <label for="password">Password</label><br>
            <input type="password" id="password" name="password" required>
        </div>
        <button type="submit">Log In</button>
    </form>

    <p>Don’t have an account? <a href="/register">Register here</a>.</p>
</section>
