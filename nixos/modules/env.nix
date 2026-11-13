{
  pkgs,
  ...
}:
let
  # (13/11) cache HF canonico: fonte unica em modules/ai/models.nix.
  # Antes so o symlink ~/.cache/huggingface apontava para o NVMe; processos
  # com HOME/cache diferente (servicos, XDG_CACHE_HOME) podiam criar cache
  # paralelo em /home. Estas vars cobrem login shells (/etc/set-environment)
  # e o home-manager as repete no environment.d do usuario.
  hfCacheDir = pkgs.aiModels.hfCacheDir;
in
{
  environment.sessionVariables = rec {
    TERMINAL = "alacritty";
    EDITOR = "nvim";
    XDG_BIN_HOME = "$HOME/.local/bin";
    PATH = [
      "${XDG_BIN_HOME}"
    ];
    HF_HOME = hfCacheDir;
    HF_HUB_CACHE = "${hfCacheDir}/hub";
    HUGGINGFACE_HUB_CACHE = HF_HUB_CACHE;
  };
}
