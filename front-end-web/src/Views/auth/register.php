<?php
// src/Views/auth/register.php
?>
<section>
    <h1>Register</h1>

    <?php if (!empty($error)): ?>
        <p role="alert" style="color: red;"><?= htmlspecialchars($error) ?></p>
    <?php endif; ?>

    <form action="/register/submit" method="POST">
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
            <label for="email">Email</label><br>
            <input
                type="email"
                id="email"
                name="email"
                required
                value="<?= htmlspecialchars($email ?? '') ?>"
            >
        </div>
        <div>
            <label for="password">Password</label><br>
            <input type="password" id="password" name="password" required>
        </div>
        <button type="submit">Register</button>
    </form>

    <p>Already have an account? <a href="/login">Log in here</a>.</p>
</section>
