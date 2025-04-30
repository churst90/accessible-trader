<?php
// index.php

declare(strict_types=1);

// 1) Bootstrap: Composer, env, config
require __DIR__ . '/config/config.php';

// 2) Load our route definitions
$routes = require __DIR__ . '/config/routes.php';

// 3) Determine the request path
$scriptName = dirname($_SERVER['SCRIPT_NAME']);
$uri        = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

// Strip the base script directory, if any
if (strpos($uri, $scriptName) === 0) {
    $path = substr($uri, strlen($scriptName));
} else {
    $path = $uri;
}

// Normalize: ensure leading slash, no trailing slash (unless root)
$path = '/' . trim($path, '/');
if ($path === '') {
    $path = '/';
}

// 4) Dispatch
if (! isset($routes[$path])) {
    header("HTTP/1.0 404 Not Found");
    echo "404 Not Found";
    exit;
}

list($controllerClass, $method) = $routes[$path];

// 5) Instantiate controller
if (! class_exists($controllerClass)) {
    header("HTTP/1.0 500 Internal Server Error");
    echo "Controller {$controllerClass} not found";
    exit;
}
$controller = new $controllerClass();

// 6) Call action
if (! method_exists($controller, $method)) {
    header("HTTP/1.0 500 Internal Server Error");
    echo "Method {$method} not found in {$controllerClass}";
    exit;
}

$controller->{$method}();
