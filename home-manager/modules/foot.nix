# Foot terminal — desabilitado, usando stylix para cores
# { pkgs, ... }: {
#   programs.foot = {
#     enable = true;
#     settings = {
#       main = {
#         font = {
#           _type = "override";
#           priority = 50;
#           content = "JetBrainsMono Nerd Font:size=12";
#         };
#         dpi-aware = "no";
#       };
#
#       colors-dark = {
#         background = "0a0a0a";
#         foreground = "00ffff";
#         regular0 = "0a0a0a";
#         regular1 = "ff5555";
#         regular2 = "50fa7b";
#         regular3 = "f1fa8c";
#         regular4 = "00cccc";
#         regular5 = "ff79c6";
#         regular6 = "8be9fd";
#         regular7 = "f8f8f2";
#         bright0 = "4d4d4d";
#         bright1 = "ff6e6e";
#         bright2 = "69ff94";
#         bright3 = "ffffa5";
#         bright4 = "00ffff";
#         bright5 = "ff92df";
#         bright6 = "a4ffff";
#         bright7 = "ffffff";
#       };
#
#       cursor = {
#         color = "00ffff 0a0a0a";
#       };
#
#       scrollback = {
#         lines = 10000;
#       };
#     };
#   };
# }
