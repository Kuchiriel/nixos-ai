{ config, pkgs, lib, ... }:

let
  cfg = config.services.jarvis-triggers;

  triggersScript = pkgs.writers.writePython3Bin "jarvis-triggers-daemon" {
    flakeIgnore = [ "E501" ];
    libraries = (ps: with ps; [ requests ]);
  } ''
    import json
    import os
    import time
    import sys
    import subprocess

    POLL_INTERVAL = ${toString cfg.pollInterval}
    STATE_DIR = os.path.expanduser("~/.local/state/jarvis")
    os.makedirs(STATE_DIR, exist_ok=True)

    def check_disk():
        """Return True if disk usage > threshold."""
        try:
            st = os.statvfs("/")
            used_pct = (1 - st.f_bavail / st.f_blocks) * 100
            return used_pct > ${toString cfg.diskThreshold}
        except Exception:
            return False

    def check_services():
        """Return list of down services."""
        down = []
        for svc in ["llama-cpp-server", "qdrant"]:
            try:
                r = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=5
                )
                if r.stdout.strip() != "active":
                    down.append(svc)
            except Exception:
                down.append(svc)
        return down

    def send_telegram(msg):
        """Send alert via Telegram if configured."""
        token = os.environ.get("JARVIS_TELEGRAM_TOKEN", "")
        chat_id = os.environ.get("JARVIS_TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        try:
            import requests
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"🤖 JARVIS Alert: {msg}"},
                timeout=10
            )
        except Exception:
            pass

    def run_checks():
        """Run all trigger checks."""
        alerts = []

        if check_disk():
            alerts.append("⚠️ Disco acima de ${toString cfg.diskThreshold}%")

        down = check_services()
        if down:
            alerts.append(f"🔴 Serviços down: {', '.join(down)}")

        if alerts:
            send_telegram("\\n".join(alerts))
            # Log to audit
            audit_path = os.path.join(STATE_DIR, "triggers-audit.jsonl")
            with open(audit_path, "a") as f:
                f.write(json.dumps({
                    "ts": time.time(),
                    "alerts": alerts,
                }) + "\\n")

    def main():
        print(f"JARVIS Triggers daemon started (poll every {POLL_INTERVAL}s)")
        while True:
            try:
                run_checks()
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL)

    if __name__ == "__main__":
        main()
  '';
in
{
  options.services.jarvis-triggers = {
    enable = lib.mkEnableOption "JARVIS triggers daemon";
    pollInterval = lib.mkOption {
      type = lib.types.int;
      default = 300;
      description = "Seconds between trigger polls";
    };
    diskThreshold = lib.mkOption {
      type = lib.types.int;
      default = 90;
      description = "Disk usage percentage to trigger alert";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ triggersScript ];

    systemd.user.services.jarvis-triggers = {
      Unit = {
        Description = "JARVIS Triggers Daemon — system condition monitoring";
        After = [ "graphical-session.target" ];
      };
      Service = {
        ExecStart = "${triggersScript}/bin/jarvis-triggers-daemon";
        Restart = "on-failure";
        RestartSec = 30;
      };
      Install = {
        WantedBy = [ "default.target" ];
      };
    };
  };
}
