<?php
// config/config.php

declare(strict_types=1);

use Dotenv\Dotenv;

// Composer autoloader
require_once __DIR__ . '/../vendor/autoload.php';

// Load .env from project root
$dotenv = Dotenv::createImmutable(__DIR__ . '/..');
$dotenv->load();

// Define app settings
define('APP_ENV', $_ENV['APP_ENV'] ?? 'production');
define('APP_DEBUG', filter_var($_ENV['APP_DEBUG'] ?? false, FILTER_VALIDATE_BOOLEAN));

// Define database settings
define('DB_CONNECTION', $_ENV['DB_CONNECTION'] ?? 'mysql');
define('DB_HOST',       $_ENV['DB_HOST']       ?? '127.0.0.1');
define('DB_PORT',       $_ENV['DB_PORT']       ?? '3306');
define('DB_DATABASE',   $_ENV['DB_DATABASE']   ?? '');
define('DB_USERNAME',   $_ENV['DB_USERNAME']   ?? '');
define('DB_PASSWORD',   $_ENV['DB_PASSWORD']   ?? '');
