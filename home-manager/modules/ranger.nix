{
  programs.ranger = {
    enable = true;
    mappings = {
      e = "edit";
    };

    settings = {
      preview_images = true;
      preview_images_method = "sixel";
      draw_borders = true;
    };

    extraConfig = ''
      set devicons
      set show_hidden
    '';
  };
}
