{ config, lib, pkgs, ... }:

let
  cfg = config.services.jarvis-wakeword;

  openwakewordPkg = pkgs.python3Packages.buildPythonPackage rec {
    pname = "openwakeword";
    version = "0.6.0";
    src = pkgs.python3Packages.fetchPypi {
      inherit pname version;
      sha256 = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    };
    propagatedBuildInputs = with pkgs.python3Packages; [
      numpy
      onnxruntime
      scipy
      requests
      sounddevice
    ];
    doCheck = false;
  };

  jarvisPythonEnv = pkgs.python3.withPackages (ps: with ps; [
    numpy
    requests
    openwakewordPkg
  ]);

  jarvisScript = pkgs.writers.writePython3Bin "jarvis-wakeword-daemon" {
    flakeIgnore = [ "E501" ];
    libraries = [ jarvisPythonEnv ];
  } ''
    import json
    import subprocess
    import time
    import numpy as np
    from openwakeword.model import Model

    RATE = 16000
    CHUNK = 512
    THRESHOLD = ${toString cfg.threshold}
    WAKEWORD_MODEL = "${config.home.homeDirectory}/.local/lib/python3.14/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx"
    STARTUP_SOUND = "${pkgs.sound-theme-freedesktop}/share/sounds/freedesktop/stereo/service-login.oga"


    def update_status(state, text=""):
        try:
            with open("/tmp/jarvis-status.json", "w") as f:
                json.dump({"state": state, "text": text}, f)
        except Exception:
            pass


    def main():
        oww = Model(wakeword_model_paths=[WAKEWORD_MODEL])
        with open("/tmp/jarvis-wakeword-status", "w") as f:
            f.write(f"READY|{time.time()}")
        update_status("initializing", "Iniciando...")
        subprocess.run(["${pkgs.libcanberra-gtk3}/bin/canberra-gtk-play", "--file", STARTUP_SOUND], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print(f"[WW] Starting arecord hw:1,7 @ {RATE}Hz (Threshold: {THRESHOLD})", flush=True)
        arecord_proc = subprocess.Popen(
            ["${pkgs.alsa-utils}/bin/arecord", "-D", "hw:1,7", "-f", "S16_LE", "-r", str(RATE), "-c", "2"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        update_status("idle", "🎤 Ouvindo...")

        while True:
            data = arecord_proc.stdout.read(CHUNK * 4)
            if not data:
                time.sleep(1)
                arecord_proc = subprocess.Popen(
                    ["${pkgs.alsa-utils}/bin/arecord", "-D", "hw:1,7", "-f", "S16_LE", "-r", str(RATE), "-c", "2"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
                continue
            audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            mono = (audio_np[::2] + audio_np[1::2]) * 0.5
            mono_norm = np.clip((mono - np.mean(mono)) * 10.0, -32768, 32767).astype(np.int16)
            predictions = oww.predict(mono_norm)

            for model_name, score in predictions.items():
                if score >= THRESHOLD:
                    print(f"[WW] Trigger detectado em {model_name} com score {score}", flush=True)


    if __name__ == "__main__":
        main()
  '';
in
{
  options.services.jarvis-wakeword = {
    enable = lib.mkEnableOption "Jarvis Wakeword Daemon";
    threshold = lib.mkOption {
      type = lib.types.float;
      default = 0.5;
      description = "Sensibilidade limite de ativação da wake word.";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ jarvisPythonEnv jarvisScript ];

    systemd.user.services.jarvis-wakeword = {
      Unit = {
        Description = "Jarvis Neural Core Wakeword Daemon";
        After = [ "graphical-session.target" ];
      };
      Service = {
        ExecStart = "${jarvisScript}/bin/jarvis-wakeword-daemon";
        Restart = "always";
        RestartSec = "5s";
      };
      Install = {
        WantedBy = [ "graphical-session.target" ];
      };
    };
  };
}
