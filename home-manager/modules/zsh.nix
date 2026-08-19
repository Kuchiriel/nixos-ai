{ pkgs, ... }:

{
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;

    history = {
      size = 10000;
      path = "$HOME/.zsh_history";
    };

    shellAliases = {
      ll = "ls -la";
      rebuild = "sudo nixos-rebuild switch --flake ~/nixos-config-reborn/#nixos-lab";
    };

    initContent = ''
      export PROMPT='%F{green}%n@%m%f:%F{blue}%~%f$ '
    '';
  };
}
