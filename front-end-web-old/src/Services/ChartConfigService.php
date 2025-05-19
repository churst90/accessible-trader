<?php
// src/Services/chartConfigService.php

namespace App\Services;
use PDO;

class ChartConfigService {
  private PDO $pdo;
  public function __construct() {
    $this->pdo = require __DIR__.'/../../config/trading_database.php';
  }

  public function load(int $userId): array {
    $stmt = $this->pdo->prepare(
      'SELECT config FROM user_configs WHERE user_id = :u'
    );
    $stmt->execute(['u' => $userId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ? json_decode($row['config'], true) : [];
  }

  public function save(int $userId, array $config): void {
    $json = json_encode($config);
    $stmt = $this->pdo->prepare(
      'INSERT INTO user_configs (user_id, config) 
         VALUES (:u, :c)
       ON CONFLICT (user_id) DO
         UPDATE SET config = EXCLUDED.config, updated_at = now()'
    );
    $stmt->execute(['u' => $userId, 'c' => $json]);
  }
}
