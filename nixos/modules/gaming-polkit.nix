# Polkit rules for JARVIS gaming mode
# Allows the user to stop/start specific system services without sudo
# during gaming mode transitions.
{pkgs, ...}: {
  security.polkit = {
    enable = true;
    extraConfig = ''
      // Allow user to manage JARVIS gaming services without password
      polkit.addRule(function(action, subject) {
        if (
          action.id == "org.freedesktop.systemd1.manage-units" &&
          subject.user == "nixos" &&
          (
            action.lookup("unit") == "llama-cpp-server.service" ||
            action.lookup("unit") == "llama-cpp-embeddings.service" ||
            action.lookup("unit") == "llama-cpp-rerank.service" ||
            action.lookup("unit") == "qdrant.service" ||
            action.lookup("unit") == "mpvpaper.service"
          ) &&
          (
            action.lookup("verb") == "start" ||
            action.lookup("verb") == "stop" ||
            action.lookup("verb") == "restart"
          )
        ) {
          return polkit.Result.YES;
        }
      });
    '';
  };
}
