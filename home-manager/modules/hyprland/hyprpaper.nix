{...}: {
  # hyprpaper DESABILITADO — conflita com mpvpaper (wallpaper animado mp4).
  # O legado Manjaro usava mpvpaper como único provider de wallpaper.
  services.hyprpaper = {
    enable = false;
  };
}
