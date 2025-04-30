<?php
// src/Controllers/ChartController.php

declare(strict_types=1);

namespace App\Controllers;

class ChartController extends Controller
{
    /** GET /chart */
    public function index(): void
    {
        // You may load any data needed for the toolbar (e.g. saved symbols) and pass as $params
        $this->render('chart');
    }
}
