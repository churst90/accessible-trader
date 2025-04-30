<?php
namespace App\Controllers;
use App\Services\ChartConfigService;

class ChartConfigController extends Controller {
  public function getConfig(): void {
    session_start();
    header('Content-Type: application/json; charset=utf-8');
    if (empty($_SESSION['user_id'])) {
      http_response_code(401);
      echo json_encode(['success'=>false,'error'=>'Not logged in']);
      return;
    }
    $svc = new ChartConfigService();
    $config = $svc->load((int)$_SESSION['user_id']);
    echo json_encode(['success'=>true,'data'=>['config'=>$config]]);
  }

  public function saveConfig(): void {
    session_start();
    header('Content-Type: application/json; charset=utf-8');
    if (empty($_SESSION['user_id'])) {
      http_response_code(401);
      echo json_encode(['success'=>false,'error'=>'Not logged in']);
      return;
    }
    $payload = json_decode(file_get_contents('php://input'), true);
    if (!is_array($payload['config'] ?? null)) {
      http_response_code(400);
      echo json_encode(['success'=>false,'error'=>'Invalid payload']);
      return;
    }
    $svc = new ChartConfigService();
    $svc->save((int)$_SESSION['user_id'], $payload['config']);
    echo json_encode(['success'=>true,'data'=>['message'=>'Config saved']]);
  }
}
