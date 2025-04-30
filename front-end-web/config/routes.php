<?php
// config/routes.php

declare(strict_types=1);

return [
    // Public pages
    '/'         => ['App\Controllers\HomeController',  'index'],
    '/chart'    => ['App\Controllers\ChartController', 'index'],
    '/faq'      => ['App\Controllers\HomeController',  'faq'],
    '/support'  => ['App\Controllers\HomeController',  'support'],

    // Auth
    '/login'    => ['App\Controllers\AuthController',  'showLoginForm'],
    '/login/submit'    => ['App\Controllers\AuthController', 'login'],
    '/register' => ['App\Controllers\AuthController',  'showRegisterForm'],
    '/register/submit' => ['App\Controllers\AuthController', 'register'],
    '/logout'   => ['App\Controllers\AuthController',  'logout'],

    // JSON API (example)
    '/api/market/exchanges'   => ['App\Controllers\ApiController', 'getExchanges'],
    '/api/market/symbols'     => ['App\Controllers\ApiController', 'getSymbols'],
    '/api/market/ohlcv'       => ['App\Controllers\ApiController', 'getOhlcv'],
    '/api/user/chart_config'       => ['App\Controllers\ChartConfigController', 'getConfig'],
    '/api/user/chart_config/save'  => ['App\Controllers\ChartConfigController', 'saveConfig'],

    // add more routes here...
];
