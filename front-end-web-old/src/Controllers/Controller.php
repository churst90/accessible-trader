<?php
// src/Controllers/Controller.php

declare(strict_types=1);

namespace App\Controllers;

abstract class Controller
{
    /**
     * Render a view within the site layout.
     *
     * @param string $view   Path to view file relative to src/Views (no “.php”)
     * @param array  $params Variables to extract for the view
     */
    protected function render(string $view, array $params = []): void
    {
        // Make each $params key available as a local variable
        extract($params, EXTR_SKIP);

        // Include the header, the view, then the footer
        require __DIR__ . '/../Views/layouts/header.php';
        require __DIR__ . "/../Views/{$view}.php";
        require __DIR__ . '/../Views/layouts/footer.php';
    }
}
