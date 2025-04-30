<?php
// src/Controllers/AuthController.php

declare(strict_types=1);

namespace App\Controllers;

class AuthController extends Controller
{
    /** Show the login form */
    public function showLoginForm(): void
    {
        $this->render('auth/login');
    }

    /** Handle login POST (/login/submit) */
    public function login(): void
    {
        session_start();
        $username = trim($_POST['username'] ?? '');
        $password = $_POST['password'] ?? '';

        $error = null;
        if ($username === '' || $password === '') {
            $error = 'Username and password are required.';
        } else {
            // Fetch user
            /** @var \PDO $pdo */
            $pdo = require __DIR__ . '/../../config/database.php';
            $stmt = $pdo->prepare('SELECT id, password_hash FROM users WHERE username = :u');
            $stmt->execute(['u' => $username]);
            $user = $stmt->fetch(PDO::FETCH_ASSOC);

            if ($user && password_verify($password, $user['password_hash'])) {
                // Authentication successful
                $_SESSION['user_id']   = $user['id'];
                $_SESSION['username']  = $username;
                $_SESSION['logged_in'] = true;

                header('Location: /');
                exit;
            }
            $error = 'Invalid username or password.';
        }

        // On error, re-render login form with $error
        $this->render('auth/login', ['error' => $error, 'username' => $username]);
    }

    /** Show the registration form */
    public function showRegisterForm(): void
    {
        $this->render('auth/register');
    }

    /** Handle register POST (/register/submit) */
    public function register(): void
    {
        session_start();
        $username = trim($_POST['username'] ?? '');
        $email    = trim($_POST['email'] ?? '');
        $password = $_POST['password'] ?? '';

        $error = null;
        if ($username === '' || $email === '' || $password === '') {
            $error = 'All fields are required.';
        } else {
            /** @var \PDO $pdo */
            $pdo = require __DIR__ . '/../../config/database.php';
            // Check existing username/email
            $stmt = $pdo->prepare('SELECT COUNT(*) FROM users WHERE username = :u OR email = :e');
            $stmt->execute(['u' => $username, 'e' => $email]);
            if ($stmt->fetchColumn() > 0) {
                $error = 'Username or email already taken.';
            } else {
                // Insert new user
                $hash = password_hash($password, PASSWORD_BCRYPT);
                $stmt = $pdo->prepare(
                    'INSERT INTO users (username, email, password_hash, role_name) 
                     VALUES (:u, :e, :p, \'user\')'
                );
                $stmt->execute([
                    'u' => $username,
                    'e' => $email,
                    'p' => $hash
                ]);

                // Log them in
                $_SESSION['user_id']   = (int)$pdo->lastInsertId();
                $_SESSION['username']  = $username;
                $_SESSION['logged_in'] = true;

                header('Location: /');
                exit;
            }
        }

        // On error, re-render register form
        $this->render('auth/register', [
            'error'    => $error,
            'username' => $username,
            'email'    => $email
        ]);
    }

    /** Log the user out */
    public function logout(): void
    {
        session_start();
        session_unset();
        session_destroy();
        header('Location: /');
        exit;
    }
}
