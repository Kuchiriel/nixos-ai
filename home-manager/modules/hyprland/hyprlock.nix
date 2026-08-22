# Hyprlock — usa lib.m3ta.colors e lib.m3ta.fonts
{lib, ...}: let
  colors = lib.m3ta.colors;
  fonts = lib.m3ta.fonts;
in {
  programs.hyprlock = {
    enable = true;
    settings = {
      general = {
        hide_cursor = true;
      };

      label = {
        text = "$TIME";
        font_size = 96;
        font_family = fonts.mono.name;
        color = "rgba(235, 219, 178, 1.0)";
        position = "0, 600";
        halign = "center";

        shadow_passes = 1;
      };

      background = [
        {
          path = "screenshot";
          blur_passes = 3;
          blur_size = 8;
          brightness = 0.6;
          contrast = 1.0;
        }
      ];

      input-field = [
        {
          size = "200, 50";
          position = "0, -80";
          monitor = "";
          dots_center = true;
          font_color = "rgb(235, 219, 178)";
          inner_color = "rgba(40, 40, 40, 0.7)";
          outer_color = "rgba(60, 56, 54, 0.8)";
          outline_thickness = 5;
          placeholder_text = "sussy baka";
          shadow_passes = 1;
          fade_on_empty = false;
        }
      ];
    };
  };
}
