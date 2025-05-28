<?php
// src/Controllers/HomeController.php

declare(strict_types=1);

namespace App\Controllers;

class HomeController extends Controller
{
    /** GET / */
    public function index(): void
    {
        $this->render('home');
    }

    /** GET /faq */
    public function faq(): void
    {
        $this->render('faq');
    }

    /** GET /support */
    public function support(): void
    {
        $this->render('support');
    }
}
