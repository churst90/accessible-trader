<?php
// config/trading_database.php
declare(strict_types=1);
use PDO, PDOException;

try {
  $dsn    = sprintf('pgsql:host=%s;port=%s;dbname=%s',
                    TRADING_DB_HOST, TRADING_DB_PORT, TRADING_DB_NAME);
  $pdo    = new PDO($dsn, TRADING_DB_USER, TRADING_DB_PASS);
  $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
  return $pdo;
} catch (PDOException $e) {
  if (APP_DEBUG) throw $e;
  die('Trading DB connection failed.');
}
