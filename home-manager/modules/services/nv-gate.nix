# nv-gate — gate de taxa para o free tier do NVIDIA
#
# O free tier do integrate.api.nvidia.com tem teto NOMINAL de 40 requests/minute
# por chave, mas o limite EFETIVO MEDIDO contra o endpoint e' ~8/min (a rampa
# com 1,5s entre requests ja tomou 429 no request #2; com 8 clientes
# concorrentes so 6 de 120 passaram na janela de 60s). O controle automatico de
# "free-tier abusers" pune rajadas — 2+ agentes simultaneos estouram isso em
# segundos (429 "Too Many Requests" matando turnos inteiros do opencode).
# O gate e' um proxy TRANSPARENTE:
#
#   * token bucket compartilhado (8 RPM, burst 2) -> rajada vira fila;
#   * 429 do upstream -> retry com backoff (honra Retry-After) -> o cliente
#     opencode ve a resposta, nao um erro;
#   * 502/503/504 e reset de conexao -> tambem retenta (o edge do NIM mata
#     prefill longo; o orcamento de tempo do gate e' MENOR que o
#     headerTimeout do opencode, entao o gate desiste antes do cliente);
#   * SSE passa em streaming (chunk a chunk, sem bufferizar);
#   * o header Authorization e' repassado intacto: o gate NAO guarda chave.
#
# Fonte dos valores: modules/ai/free-providers.json (providers.nvidia.gate).
# Medicao do teto real: opencode/NVIDIA_NIM_GROUND_TRUTH.md §5 (repo Kuchiriel/mt5).
{ config, lib, pkgs, ... }:
let
  catalog = builtins.fromJSON (builtins.readFile ../../../modules/ai/free-providers.json);
  gate = catalog.providers.nvidia.gate or { enabled = false; };
in
{
  systemd.user.services.nv-gate = {
    Unit = {
      Description = "nv-gate — token bucket + retry de 429/502/503/504 para o free tier NVIDIA";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      Type = "simple";
      ExecStart = lib.concatStringsSep " " [
        "${pkgs.python3}/bin/python3"
        (pkgs.writeText "nv-gate.py" (builtins.readFile ../../../scripts/nv-gate.py))
        "--port"
        (toString (gate.port or 8095))
        "--rpm"
        (toString (gate.rpm or 8))
        "--burst"
        (toString (gate.burst or 2))
        "--retry-budget"
        (toString (gate.retry_budget or 480))
        "--upstream"
        (gate.upstream or "https://integrate.api.nvidia.com")
      ];
      Restart = "always";
      RestartSec = 3;
    };
    Install = {
      WantedBy = [ "default.target" ];
    };
  };
}
