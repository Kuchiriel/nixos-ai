{
  programs.waybar = {
    enable = true;
    style = ./style.css;
    settings = {
      mainBar = {
        layer = "top";
        position = "top";
        height = 34;
        spacing = 10;

        modules-left = [
          "hyprland/workspaces"
          "hyprland/window"
        ];

        modules-center = [
          "clock"
        ];

        modules-right = [
          "custom/files"
          "cpu"
          "memory"
          "backlight"
          "battery"
          "network"
          "bluetooth"
          "pulseaudio"
          "tray"
        ];

        "hyprland/workspaces" = {
          format = "{name} {windows}";
          window-rewrite-default = "󱓡";
          on-click = "activate";
          window-rewrite = {
            "title<.*youtube.*>" = "󰗃";
            "class<firefox>" = "";
            "class<foot>" = "";
            "class<code-oss>" = "󰨞";
            "class<pcmanfm-qt>" = "󰉋";
            "class<discord>" = "󰙯";
            "class<spotify>" = "";
          };
        };

        "hyprland/window" = {
          format = "󰖲 {title}";
          max-length = 40;
          separate-outputs = true;
        };

        "clock" = {
          format = " {:%H:%M}";
          tooltip = false;
          on-click = "foot --app-id floating_shell -e calcurse";
        };

        "custom/files" = {
          format = "󰉋 Files";
          tooltip = "File Manager (yazi)";
          on-click = "foot --app-id floating_shell -e yazi";
        };

        "cpu" = {
          interval = 2;
          format = " {usage}%";
          tooltip = false;
          on-click = "foot --app-id floating_shell -e btm";
        };

        "memory" = {
          interval = 2;
          format = " {used:0.1f}G";
          tooltip = false;
          on-click = "foot --app-id floating_shell -e btm";
        };

        "backlight" = {
          format = "󰃠 {percent}%";
          tooltip = false;
          on-scroll-up = "brightnessctl set +5%";
          on-scroll-down = "brightnessctl set 5%-";
        };

        "battery" = {
          format = "{icon} {capacity}%";
          format-icons = ["" "" "" "" ""];
          tooltip = false;
        };

        "network" = {
          format-wifi = " {essid}";
          format-ethernet = "󰈀 Wired";
          tooltip = false;
          on-click = "foot --app-id floating_shell -e nmtui";
        };

        "bluetooth" = {
          format = " {status}";
          tooltip = false;
          on-click = "foot --app-id floating_shell -e bluetuith";
        };

        "pulseaudio" = {
          format = "{icon} {volume}%";
          format-icons = {
            "headphone" = "";
            "hands-free" = "";
            "headset" = "";
            "phone" = "";
            "portable" = "";
            "car" = "";
            "default" = ["" "" ""];
          };
          tooltip = false;
          on-click = "pavucontrol";
        };

        "tray" = {
          icon-size = 18;
          spacing = 6;
        };
      };
    };
  };
}
