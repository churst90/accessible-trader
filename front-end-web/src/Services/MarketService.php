// src/Services/MarketService.php
<?php
declare(strict_types=1);

namespace App\Services;

use PDO;

class MarketService
{
    private PDO $pdo;

    public function __construct()
    {
        // Load the PDO instance
        $this->pdo = require __DIR__ . '/../../config/database.php';
    }

    /**
     * Return a list of available exchanges for a given market.
     */
    public function fetchExchanges(string $market): array
    {
        if ($market === '') {
            return [];
        }

        $stmt = $this->pdo->prepare(
            'SELECT DISTINCT exchange
               FROM exchange_symbols
              WHERE market = :m
           ORDER BY exchange'
        );
        $stmt->execute(['m' => $market]);
        return $stmt->fetchAll(PDO::FETCH_COLUMN) ?: [];
    }

    /**
     * Return a list of symbols for a given market/exchange.
     */
    public function fetchSymbols(string $market, string $exchange): array
    {
        if ($market === '' || $exchange === '') {
            return [];
        }

        $stmt = $this->pdo->prepare(
            'SELECT symbol
               FROM exchange_symbols
              WHERE market = :m
                AND exchange = :e
           ORDER BY symbol'
        );
        $stmt->execute(['m' => $market, 'e' => $exchange]);
        return $stmt->fetchAll(PDO::FETCH_COLUMN) ?: [];
    }

    /**
     * Fetch OHLCV data, optionally filtered by since/before.
     *
     * @param string   $market
     * @param string   $exchange
     * @param string   $symbol
     * @param string   $timeframe  e.g. '1m', '5m', '1h', '1d'
     * @param int      $limit      maximum bars to return
     * @param int|null $since      earliest timestamp in ms (inclusive)
     * @param int|null $before     latest timestamp in ms (exclusive)
     *
     * @return array [ohlcArray, volumeArray]
     */
    public function fetchOhlcv(
        string $market,
        string $exchange,
        string $symbol,
        string $timeframe,
        int    $limit,
        ?int   $since = null,
        ?int   $before = null
    ): array {
        if ($market === '' || $exchange === '' || $symbol === '' || $timeframe === '') {
            return [[], []];
        }

        // Decide raw vs continuous-agg table
        $table = $timeframe === '1m'
               ? 'ohlcv_data'
               : "ohlcv_{$timeframe}";

        // Build base SQL
        $sql = "
          SELECT
            EXTRACT(EPOCH FROM timestamp)::BIGINT * 1000 AS ts,
            open, high, low, close, volume
          FROM {$table}
         WHERE market = :m
           AND exchange = :e
           AND symbol = :s
        ";

        // Bind parameters
        $params = [
            'm' => $market,
            'e' => $exchange,
            's' => $symbol,
        ];

        if ($since !== null) {
            $sql    .= " AND timestamp >= to_timestamp(:since/1000)";
            $params['since'] = $since;
        }
        if ($before !== null) {
            $sql     .= " AND timestamp < to_timestamp(:before/1000)";
            $params['before'] = $before;
        }

        $sql .= "
         ORDER BY timestamp ASC
         LIMIT :l
        ";

        $stmt = $this->pdo->prepare($sql);
        $stmt->bindValue('m', $market);
        $stmt->bindValue('e', $exchange);
        $stmt->bindValue('s', $symbol);
        if ($since !== null) {
            $stmt->bindValue('since', $since, PDO::PARAM_INT);
        }
        if ($before !== null) {
            $stmt->bindValue('before', $before, PDO::PARAM_INT);
        }
        $stmt->bindValue('l', $limit, PDO::PARAM_INT);
        $stmt->execute();

        $ohlc   = [];
        $volume = [];
        while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
            $ts = (int)$row['ts'];
            $ohlc[]   = [
                $ts,
                (float)$row['open'],
                (float)$row['high'],
                (float)$row['low'],
                (float)$row['close']
            ];
            $volume[] = [$ts, (float)$row['volume']];
        }

        return [$ohlc, $volume];
    }
}
