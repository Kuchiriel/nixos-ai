# wireplumber-default-source — DEFAULT SOURCE do pipewire = o mic DIGITAL
#
# Por que (medido 03/11, sintoma "falo com ele e nada"):
#   O Stereo Mic (Mic2) deste notebook está MORTO (rms 0,000257 vs 0,005585
#   do Digital = 27 dB abaixo). O módulo AEC3 (echo-cancel) captura do
#   DEFAULT SOURCE: com o Mic2 no default, o AEC3/RNNoise recebiam SILÊNCIO
#   e o duplex gravava rms=0 — o microfone "surdo".
#
# Por que uma unit e não config do wireplumber:
#   O WirePlumber 0.5 (0.5.14 no gen 372) reescreveu o daemon em LUA e o
#   formato antigo de `.rules` (match.properties / actions.default_source)
#   NÃO EXISTE mais. No 0.5 o default é decidido por:
#     - `default.configured.audio.source` — o que o usuário escolheu, guardado
#       POR NOME em ~/.local/state/wireplumber/default-nodes, com prioridade
#       30000+ (find-selected-default-node.lua) ⇒ vence do "melhor por
#       priority.session";
#     - senão, o de maior priority.session (o Mic2 ganha: 1648 do driver
#       contra o perfil do cAVS).
#   A unit re-afirma essa escolha no login, resolvendo o node pelo NOME
#   (o índice 73/74 muda entre boots) e gravando o `default.configured.*`.
#
# Idempotente: se já for o certo, não faz nada.
{ config, lib, pkgs, ... }:

let
  # node.name do cAVS Digital Microphone — ESTÁVEL (PCI path), diferente do
  # índice (que muda entre boots).
  targetNode = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source";

  resolver = pkgs.writeText "wireplumber-default-source.sh" ''
    #!/bin/sh
    # $1 = node.name alvo. Resolve o id pelo nome (pw-cli) e fixa como
    # default source (wpctl). Idempotente: repetir é barato e o
    # wireplumber só grava o default.configured.* quando muda.
    set -u
    target="$1"
    pw_cli=${pkgs.pipewire}/bin/pw-cli
    wpctl=${pkgs.wireplumber}/bin/wpctl
    awk_bin=${pkgs.gawk}/bin/awk
    seq_bin=${pkgs.coreutils}/bin/seq
    sleep_bin=${pkgs.coreutils}/bin/sleep

    for _i in $("$seq_bin" 1 30); do
      id=$("$pw_cli" ls Node 2>/dev/null | "$awk_bin" -v target="$target" '
        /^\tid [0-9]+, type/ { id=$2; sub(/,$/, "", id); name="" }
        $1 == "node.name" { gsub(/"/, "", $3); name=$3 }
        name == target && id != "" { print id; exit }
      ')
      if [ -n "${id:-}" ]; then
        if "$wpctl" set-default "$id"; then
          echo "default source -> $target (id $id)"
        fi
        exit 0
      fi
      "$sleep_bin" 1
    done
    echo "wireplumber-default-source: node $target não apareceu em 30s" >&2
    exit 0
  '';
in
{
  systemd.user.services.wireplumber-default-source = {
    Unit = {
      Description = "Fixa o mic DIGITAL (Mic1) como default source do pipewire";
      After = [ "pipewire.service" "wireplumber.service" ];
      Wants = [ "pipewire.service" ];
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${resolver} ${targetNode}";
      RemainAfterExit = true;
    };
    Install = {
      WantedBy = [ "default.target" ];
    };
  };
}
