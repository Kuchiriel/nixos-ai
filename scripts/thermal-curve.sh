#!/usr/bin/env bash
# thermal-curve.sh — Measure thermal degradation over 5 minutes of continuous inference
set -euo pipefail

LLAMA_BIN=/home/nixos/projects/llama-wackmall/build/bin/llama-server
MODEL=/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
MMPROJ=/nix/store/fc4lc40lbcp1mi0vqq4d4780d8vf3w5p-mmproj-BF16.gguf
PORT=8080
DURATION=${1:-300}  # seconds
SAMPLE_INTERVAL=2   # seconds

export LD_LIBRARY_PATH="/run/opengl-driver/lib"

PROMPT='Write a detailed analysis of computational complexity theory, covering P vs NP, NP-completeness, and practical implications for algorithm design.'

# ── helpers ──────────────────────────────────────────────────────────
get_full_snapshot() {
    local pid=$1
    local elapsed=$2
    
    # CPU frequency in kHz (P-cores cpu4-7, E-cores cpu0-3)
    local pcore_max=0 ecore_max=0
    for i in 4 5 6 7; do
        local f=$(cat /sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq 2>/dev/null | tr -d '[:space:]' || echo "0")
        if [ "$f" -gt "$pcore_max" ] 2>/dev/null; then pcore_max=$f; fi
    done
    for i in 0 1 2 3; do
        local f=$(cat /sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq 2>/dev/null | tr -d '[:space:]' || echo "0")
        if [ "$f" -gt "$ecore_max" ] 2>/dev/null; then ecore_max=$f; fi
    done
    
    # CPU temperature (millidegrees to degrees)
    local cpu_temp=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -1 | tr -d '\n' || echo "0")
    cpu_temp=$((cpu_temp / 1000))
    
    # CPU power (from RAPL if available)
    local cpu_power=$(cat /sys/class/powercap/intel-rapl:0/energy_uj 2>/dev/null || echo "0")
    
    # GPU stats
    local gpu_stats=$(nvidia-smi --query-gpu=clocks.current.sm,clocks.current.memory,temperature.gpu,power.draw,utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
    local gpu_sm=$(echo "$gpu_stats" | cut -d, -f1 | tr -d ' ')
    local gpu_mem=$(echo "$gpu_stats" | cut -d, -f2 | tr -d ' ')
    local gpu_temp=$(echo "$gpu_stats" | cut -d, -f3 | tr -d ' ')
    local gpu_power=$(echo "$gpu_stats" | cut -d, -f4 | tr -d ' ')
    local gpu_util=$(echo "$gpu_stats" | cut -d, -f5 | tr -d ' ')
    local vram=$(echo "$gpu_stats" | cut -d, -f6 | tr -d ' ')
    
    # RAM
    local ram_used=$(free -m | awk '/Mem:/{print $3}')
    
    # Page faults
    local stat=$(cat /proc/$pid/stat 2>/dev/null || echo "")
    local minfaults=0 majfaults=0
    if [ -n "$stat" ]; then
        local fields=($stat)
        minfaults=${fields[9]}
        majfaults=${fields[11]}
    fi
    
    echo "${elapsed},${ecore_max},${pcore_max},${cpu_temp},${gpu_sm},${gpu_mem},${gpu_temp},${gpu_power},${gpu_util},${vram},${ram_used},${minfaults},${majfaults}"
}

wait_server() {
    local max_wait=60 i=0
    while [ $i -lt $max_wait ]; do
        curl -sf http://127.0.0.1:$PORT/health >/dev/null 2>&1 && return 0
        sleep 2; i=$((i+2))
    done
    return 1
}

# ── main ─────────────────────────────────────────────────────────────
echo "=== Thermal Curve Measurement ==="
echo "Duration: ${DURATION}s, Sample interval: ${SAMPLE_INTERVAL}s"
echo ""

# Stop existing service
sudo systemctl stop llama-cpp-server.service 2>/dev/null || true
sleep 3

# Start server
setsid $LLAMA_BIN \
    -m "$MODEL" --mmproj "$MMPROJ" \
    --host 0.0.0.0 --port $PORT \
    -c 8192 -t 8 -b 512 -ub 512 -ngl 45 \
    -fa on -ctk q4_0 -ctv q4_0 \
    -ehs 25 --split-mode layer \
    --parallel 1 --jinja \
    </dev/null >/tmp/llama-thermal.log 2>&1 &

server_pid=$!
echo "Server PID: $server_pid"

if ! wait_server; then
    echo "FAILED: server didn't start"
    kill -9 $server_pid 2>/dev/null || true
    exit 1
fi

echo "Server ready. Starting thermal monitoring..."

# CSV header
echo "elapsed_s,ecore_mhz,pcore_mhz,cpu_temp_c,gpu_sm_mhz,gpu_mem_mhz,gpu_temp_c,gpu_power_w,gpu_util_pct,vram_mb,ram_mb,minfaults,majfaults,tokens,elapsed_ms,ms_per_token,tok_per_sec" > /tmp/thermal-curve.csv

# Background clock sampler
(
    start_time=$(date +%s)
    while kill -0 $server_pid 2>/dev/null; do
        elapsed=$(( $(date +%s) - start_time ))
        snapshot=$(get_full_snapshot $server_pid $elapsed)
        echo "$snapshot,,,,,,,,,," >> /tmp/thermal-clock-samples.csv
        sleep $SAMPLE_INTERVAL
    done
) &
sampler_pid=$!

# Continuous inference loop
start_time=$(date +%s)
run_count=0

echo "Starting continuous inference for ${DURATION}s..."
echo ""

while true; do
    elapsed=$(( $(date +%s) - start_time ))
    [ $elapsed -ge $DURATION ] && break
    
    run_count=$((run_count + 1))
    
    # Measure a single generation
    start_ns=$(date +%s%N)
    response=$(curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"qwen\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}],\"max_tokens\":100,\"temperature\":0}" 2>/dev/null)
    end_ns=$(date +%s%N)
    
    elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
    completion_tokens=$(echo "$response" | grep -o '"completion_tokens":[0-9]*' | cut -d: -f2 || echo "100")
    
    if [ "$elapsed_ms" -gt 0 ] && [ "$completion_tokens" -gt 0 ] 2>/dev/null; then
        ms_per_token=$(echo "scale=2; $elapsed_ms / $completion_tokens" | bc 2>/dev/null || echo "0")
        tok_per_sec=$(echo "scale=2; $completion_tokens * 1000 / $elapsed_ms" | bc 2>/dev/null || echo "0")
    else
        ms_per_token=0; tok_per_sec=0
    fi
    
    # Get snapshot at this moment
    snapshot=$(get_full_snapshot $server_pid $elapsed)
    
    # Append to CSV
    echo "${snapshot},${completion_tokens},${elapsed_ms},${ms_per_token},${tok_per_sec}" >> /tmp/thermal-curve.csv
    
    printf "\r[%3ds/%ds] Run %d: %s tok/s, %s ms/tok, CPU=%sMHz GPU=%sMHz GPU=%s°C GPU=%sW" \
        $elapsed $DURATION $run_count "$tok_per_sec" "$ms_per_token" \
        "$(echo $snapshot | cut -d, -f3)" \
        "$(echo $snapshot | cut -d, -f5)" \
        "$(echo $snapshot | cut -d, -f7)" \
        "$(echo $snapshot | cut -d, -f8)"
    
    # Small delay to avoid overwhelming the server
    sleep 1
done

echo ""
echo ""

# Stop monitoring
kill $sampler_pid 2>/dev/null || true
wait $sampler_pid 2>/dev/null || true

# Stop server
kill $server_pid 2>/dev/null || true
wait $server_pid 2>/dev/null || true

echo "=== THERMAL CURVE RESULTS ==="
echo ""

# Analysis
awk -F, 'NR>1 && $17>0 {
    t=$1; pcore=$3; cpu_t=$4; gpu_sm=$5; gpu_t=$7; gpu_p=$8; tps=$17; mpt=$16
    
    # Track transitions
    if (t <= 30) phase="COLD"
    else if (t <= 60) phase="WARM"
    else if (t <= 120) phase="PEAK"
    else phase="STEADY"
    
    # First throttle detection
    if (!throttle_detected && pcore < 3500000 && t > 10) {
        printf "\n*** FIRST THROTTLE at %ds: CPU=%d MHz, GPU=%d MHz, GPU=%dW ***\n", t, pcore, gpu_sm, gpu_p
        throttle_detected=1
        throttle_time=t
        throttle_cpu=pcore
        throttle_gpu=gpu_sm
        throttle_gpu_p=gpu_p
    }
    
    # Print key timestamps
    if (t==0 || t==10 || t==20 || t==30 || t==60 || t==90 || t==120 || t==180 || t==240 || t==300 || t==throttle_time) {
        printf "%4ds | CPU: %6d MHz %3d°C | GPU: %5d MHz %3d°C %5.1fW | %6.2f tok/s %6.1f ms/tok\n", \
            t, pcore, cpu_t, gpu_sm, gpu_t, gpu_p, tps, mpt
    }
    
    # Accumulate for phases
    if (phase == "COLD") { cold_sum+=mpt; cold_n++ }
    else if (phase == "STEADY") { steady_sum+=mpt; steady_n++ }
}
END {
    printf "\n=== PHASE AVERAGES ===\n"
    if (cold_n>0) printf "COLD   (0-30s):  avg %.1f ms/tok (%.1f tok/s)\n", cold_sum/cold_n, 1000/(cold_sum/cold_n)
    if (steady_n>0) printf "STEADY (>120s): avg %.1f ms/tok (%.1f tok/s)\n", steady_sum/steady_n, 1000/(steady_sum/steady_n)
    if (cold_n>0 && steady_n>0) {
        ratio = (steady_sum/steady_n) / (cold_sum/cold_n)
        printf "Degradation: %.1fx slower in steady state\n", ratio
    }
}' /tmp/thermal-curve.csv

echo ""
echo "=== FULL DATA ==="
cat /tmp/thermal-curve.csv | column -t -s,

# Restart normal service
sudo systemctl start llama-cpp-server.service 2>/dev/null || true
echo ""
echo "=== DONE ==="
