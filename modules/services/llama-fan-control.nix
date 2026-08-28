# =============================================================================
# Fan Control for llama.cpp Inference
# =============================================================================
# Acer Nitro V15 (ANV15-51) não expõe controle de ventoinha via hwmon.
# O módulo acer_wmi precisa do parâmetro predator_v4=1 para habilitar
# controle de fan via sysfs. Quando habilitado, este serviço força
# a ventoinha no máximo sempre que o llama-server estiver rodando.
#
# Requisitos:
#   boot.kernelParams = [ "acer_wmi.predator_v4=1" ];
#
# O serviço monitora o PID do llama-server e controla a ventoinha
# via /sys/class/hwmon/hwmonX/ (onde X é o hwmon do acer_wmi).
# =============================================================================

{ config, pkgs, lib, ... }:

with lib;

let
  cfg = config.services.llama-fan-control;

  # Script que detecta e controla a ventoinha
  fanControlScript = pkgs.writeShellScript "llama-fan-control" ''
    set -euo pipefail

    HWMON_DIR=""
    MAX_FAN=255
    CHECK_INTERVAL=5

    find_acer_hwmon() {
      for hwmon in /sys/class/hwmon/hwmon*; do
        if [ -f "$hwmon/name" ] && grep -q "acer" "$hwmon/name" 2>/dev/null; then
          if [ -f "$hwmon/pwm1_enable" ]; then
            echo "$hwmon"
            return 0
          fi
        fi
      done
      return 1
    }

    set_fan_turbo() {
      local hwmon="$1"
      echo 0 > "$hwmon/pwm1_enable" 2>/dev/null || true  # 0 = Turbo
      echo $MAX_FAN > "$hwmon/pwm1" 2>/dev/null || true
      # GPU fan se disponível
      echo 0 > "$hwmon/pwm2_enable" 2>/dev/null || true
      echo $MAX_FAN > "$hwmon/pwm2" 2>/dev/null || true
    }

    set_fan_auto() {
      local hwmon="$1"
      echo 2 > "$hwmon/pwm1_enable" 2>/dev/null || true  # 2 = Auto
      echo 2 > "$hwmon/pwm2_enable" 2>/dev/null || true
    }

    log() {
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    }

    log "Fan control daemon started"

    HWMON_DIR=$(find_acer_hwmon) || {
      log "WARNING: acer_wmi hwmon not found. Fan control unavailable."
      log "Ensure 'acer_wmi.predator_v4=1' is in kernel params."
      log "Falling back to thermald adaptive mode."
      # Keep running to log, but don't attempt control
      while true; do sleep 300; done
    }

    log "Found acer hwmon at: $HWMON_DIR"

    was_running=false

    while true; do
      # Check if llama-server (main LLM) is running
      if pgrep -x "llama-server" > /dev/null 2>&1; then
        if [ "$was_running" = false ]; then
          log "llama-server detected — switching to TURBO fan"
          set_fan_turbo "$HWMON_DIR"
          was_running=true

          # Log thermal state
          if [ -f "$HWMON_DIR/temp1_input" ]; then
            log "CPU temp: $(cat "$HWMON_DIR/temp1_input" 2>/dev/null) m°C"
          fi
          if [ -f "$HWMON_DIR/fan1_input" ]; then
            log "CPU fan: $(cat "$HWMON_DIR/fan1_input" 2>/dev/null) RPM"
          fi
          if [ -f "$HWMON_DIR/fan2_input" ]; then
            log "GPU fan: $(cat "$HWMON_DIR/fan2_input" 2>/dev/null) RPM"
          fi
        fi
      else
        if [ "$was_running" = true ]; then
          log "llama-server stopped — switching to AUTO fan"
          set_fan_auto "$HWMON_DIR"
          was_running=false
        fi
      fi
      sleep $CHECK_INTERVAL
    done
  '';

  # Script de diagnóstico para verificar se o fan control está disponível
  fanDiagScript = pkgs.writeShellScript "llama-fan-diag" ''
    set -euo pipefail

    echo "=== Fan Control Diagnostics ==="
    echo ""

    echo "1. Kernel parameter check:"
    if grep -q "predator_v4" /proc/cmdline 2>/dev/null; then
      echo "   ✅ acer_wmi.predator_v4=1 found in cmdline"
    else
      echo "   ❌ acer_wmi.predator_v4=1 NOT in kernel params"
      echo "   Add: boot.kernelParams = [ \"acer_wmi.predator_v4=1\" ];"
    fi

    echo ""
    echo "2. acer_wmi module status:"
    if lsmod | grep -q acer_wmi; then
      echo "   ✅ acer_wmi loaded"
      echo "   Parameters: $(cat /sys/module/acer_wmi/parameters/* 2>/dev/null | tr '\n' ' ')"
    else
      echo "   ❌ acer_wmi not loaded"
    fi

    echo ""
    echo "3. hwmon detection:"
    FOUND=false
    for hwmon in /sys/class/hwmon/hwmon*; do
      name=$(cat "$hwmon/name" 2>/dev/null || echo "unknown")
      if echo "$name" | grep -qi "acer"; then
        echo "   ✅ Found: $hwmon ($name)"
        echo "   Files: $(ls "$hwmon"/pwm* "$hwmon"/fan* 2>/dev/null | xargs -I{} basename {} | tr '\n' ' ')"
        FOUND=true
      fi
    done
    if [ "$FOUND" = false ]; then
      echo "   ❌ No acer hwmon found"
      echo "   Available hwmons:"
      for hwmon in /sys/class/hwmon/hwmon*; do
        echo "     $(cat "$hwmon/name" 2>/dev/null): $hwmon"
      done
    fi

    echo ""
    echo "4. Current fan state:"
    for c in /sys/class/thermal/cooling_device*/; do
      type=$(cat "''${c}type" 2>/dev/null)
      cur=$(cat "''${c}cur_state" 2>/dev/null)
      max=$(cat "''${c}max_state" 2>/dev/null)
      if [ "$max" != "0" ]; then
        echo "   $type: $cur/$max"
      fi
    done

    echo ""
    echo "5. Thermal state:"
    nvidia-smi --query-gpu=temperature.gpu,clocks.current.graphics,power.draw,utilization.gpu --format=csv,noheader 2>/dev/null && true
    for zone in /sys/class/thermal/thermal_zone*/; do
      type=$(cat "''${zone}type" 2>/dev/null)
      temp=$(cat "''${zone}temp" 2>/dev/null)
      echo "   $type: $temp"
    done

    echo ""
    echo "6. llama-server status:"
    if pgrep -x llama-server > /dev/null 2>&1; then
      echo "   ✅ Running (PID: $(pgrep -x llama-server | head -1))"
      echo "   Runtime: $(ps -p $(pgrep -x llama-server | head -1) -o etime= 2>/dev/null)"
    else
      echo "   ⬜ Not running"
    fi
  '';
in {
  options.services.llama-fan-control = {
    enable = mkEnableOption "Fan control for llama.cpp inference";
    checkInterval = mkOption {
      type = types.int;
      default = 5;
      description = "Seconds between checks for llama-server status";
    };
  };

  config = mkIf cfg.enable {
    systemd.services.llama-fan-control = {
      description = "Fan turbo control for llama.cpp inference";
      after = [ "llama-cpp-server.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = fanControlScript;
        Restart = "always";
        RestartSec = 10;
        # Don't kill the fan when service stops — revert to auto first
        ExecStopPost = pkgs.writeShellScript "fan-revert" ''
          # Find acer hwmon and revert to auto
          for hwmon in /sys/class/hwmon/hwmon*; do
            if [ -f "$hwmon/name" ] && grep -q "acer" "$hwmon/name" 2>/dev/null; then
              if [ -f "$hwmon/pwm1_enable" ]; then
                echo 2 > "$hwmon/pwm1_enable" 2>/dev/null || true
                echo 2 > "$hwmon/pwm2_enable" 2>/dev/null || true
              fi
            fi
          done
        '';
      };
    };

    # Expose diagnostic command
    environment.systemPackages = [
      (pkgs.runCommand "llama-fan-diag" {
        propagatedBuildInputs = [ fanDiagScript ];
      } ''
        mkdir -p $out/bin
        cp ${fanDiagScript} $out/bin/llama-fan-diag
      '')
    ];
  };
}
