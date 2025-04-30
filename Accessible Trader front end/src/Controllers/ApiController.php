// src/Controllers/ApiController.php
<?php
declare(strict_types=1);

namespace App\Controllers;

use App\Services\MarketService;

class ApiController extends Controller
{
    /** GET /api/market/exchanges?market=crypto|stocks */
    public function getExchanges(): void
    {
        header('Content-Type: application/json; charset=utf-8');

        $market = $_GET['market'] ?? '';
        $svc    = new MarketService();
        $list   = $svc->fetchExchanges($market);

        echo json_encode([
            'success' => true,
            'data'    => ['exchanges' => $list]
        ]);
    }

    /** GET /api/market/symbols?market=…&exchange=… */
    public function getSymbols(): void
    {
        header('Content-Type: application/json; charset=utf-8');

        $market   = $_GET['market']   ?? '';
        $exchange = $_GET['exchange'] ?? '';
        $svc      = new MarketService();
        $list     = $svc->fetchSymbols($market, $exchange);

        echo json_encode([
            'success' => true,
            'data'    => ['symbols' => $list]
        ]);
    }

    /**
     * GET /api/market/ohlcv
     *   Required: market, exchange, symbol, timeframe
     *   Optional: limit, since (ms), before (ms)
     */
    public function getOhlcv(): void
    {
        header('Content-Type: application/json; charset=utf-8');

        $market    = $_GET['market']    ?? '';
        $exchange  = $_GET['exchange']  ?? '';
        $symbol    = $_GET['symbol']    ?? '';
        $timeframe = $_GET['timeframe'] ?? '';
        $limit     = (int)($_GET['limit'] ?? 100);
        $since     = isset($_GET['since'])  ? (int)$_GET['since']  : null;
        $before    = isset($_GET['before']) ? (int)$_GET['before'] : null;

        $svc = new MarketService();
        [$ohlc, $volume] = $svc->fetchOhlcv(
            $market,
            $exchange,
            $symbol,
            $timeframe,
            $limit,
            $since,
            $before
        );

        echo json_encode([
            'success' => true,
            'data'    => [
                'ohlc'   => $ohlc,
                'volume' => $volume
            ]
        ]);
    }
}
