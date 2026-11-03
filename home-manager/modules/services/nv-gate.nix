# nv-gate — gate de taxa para o free tier do NVIDIA (40 RPM por chave)
#
# O free tier do integrate.api.nvidia.com responde 40 requests/minute por
# chave e o controle automatico de "free-tier abusers" pune rajadas — 2+ agentes
# simultâneos estouram isso em segundos (429 "Too Many Requests" matando
# turnos inteiros do opencode). O gate é um proxy TRANSPARENTE:
#
#   * token bucket compartilhado (24 RPM, burst 4) -> rajada vira fila;
#   * 429 do upstream -> retry com backoff (honra Retry-After) -> o cliente
#     opencode ve a resposta, nao um erro;
#   * SSE passa em streaming (chunk a chunk, sem bufferizar);
#   * o header Authorization e repassado intacto: o gate NAO guarda chave.
#
# Fonte dos valores: modules/ai/free-providers.json (providers.nvidia.gate).
{ config, lib, pkgs, ... }:
let
  catalog = builtins.fromJSON (builtins.readFile ../../../modules/ai/free-providers.json);
  gate = catalog.providers.nvidia.gate or { enabled = false; };
in
{
  systemd.user.services.nv-gate = {
    Unit = {
      Description = "nv-gate — token bucket + retry de 429 para o free tier NVIDIA";
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
        (toString (gate.rpm or 24))
        "--burst"
        (toString (gate.burst or 4))
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
