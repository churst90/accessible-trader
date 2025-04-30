<?php
// config/database.php

declare(strict_types=1);

use PDO;
use PDOException;

// Assumes config/config.php has already been required,
// so the DB_* constants are defined.

try {
    if (DB_CONNECTION === 'pgsql') {
        // PostgreSQL DSN
        $dsn = sprintf(
            'pgsql:host=%s;port=%s;dbname=%s',
            DB_HOST,
            DB_PORT,
            DB_DATABASE
        );
    } else {
        // MySQL fallback
        $dsn = sprintf(
            'mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4',
            DB_HOST,
            DB_PORT,
            DB_DATABASE
        );
    }

    $pdo = new PDO($dsn, DB_USERNAME, DB_PASSWORD);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

    return $pdo;
} catch (PDOException $e) {
    if (APP_DEBUG) {
        // In development, show full error
        throw $e;
    }
    // In production, a generic message
    die('Database connection failed.');
}
