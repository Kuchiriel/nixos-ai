# Overlay para pacotes m3ta-nixpkgs
#
# Este overlay importa os pacotes sidecar, stt-ptt e talk do m3ta-nixpkgs
# (submodule apontando para o repositório nixpkgs principal).
#
# As dependências são resolvidas via `final.callPackage` para garantir
# que pacotes como opencode, td, tmux, whisper-cpp etc. venham do
# closure completo do flake.

{ inputs, ... }:

final: prev: let
  m3ta = "${inputs.m3ta-nixpkgs}";
in {
  # sidecar: terminal multiplexer/UX para CLI agents (Go)
  # Dependências: opencode, td, tmux
  sidecar = final.callPackage "${m3ta}/pkgs/sidecar" {
    opencode = final.opencode;
    td = final.td;
    tmux = final.tmux;
  };

  # stt-ptt: Push-to-Talk Speech-to-Text (Bash + Whisper)
  # Dependências: whisper-cpp, wtype, libnotify, pipewire, procps, busybox
  stt-ptt = final.callPackage "${m3ta}/pkgs/stt-ptt" {
    whisper-cpp = final.whisper-cpp;
  };

  # talk: Text-to-Speech com ElevenLabs (Bash + Python)
  # Dependências: curl, python3, mpv, libnotify, busybox, fetchurl
  talk = final.callPackage "${m3ta}/pkgs/talk" {
    mpv = final.mpv;
  };
}
