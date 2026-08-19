{ pkgs, ... }: {
  programs.neovim = {
    enable = true;
    # 26.05 mudou os defaults p/ false (stateVersion < 26.05 mantém true);
    # fixamos explicitamente o comportamento atual (providers ruby/python3).
    withRuby = true;
    withPython3 = true;
    extraPackages = with pkgs; [
      lua-language-server
      python3Packages.python-lsp-server
      nixd
      vimPlugins.nvim-treesitter-parsers.hyprlang
    ];
  };
}
