#!/usr/bin/env bash
# proper-benchmark.sh — 10-run benchmark with CPU/GPU clock monitoring
# Validates methodology and measures hardware state during inference
set -euo pipefail

LLAMA_BIN=/home/nixos/projects/llama-wackmall/build/bin/llama-server
MODEL=/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
MMPROJ=/nix/store/fc4lc40lbcp1mi0vqq4d4780d8vf3w5p-mmproj-BF16.gguf
PORT=8080
RUNS=${1:-10}
GEN_TOKENS=100

export LD_LIBRARY_PATH="/run/opengl-driver/lib"

# Fixed prompt for reproducibility
PROMPT='Write a concise summary of computational complexity theory.'

# ── helpers ──────────────────────────────────────────────────────────
get_cpu_freq() {
    # Get P-core (cpu4-7) and E-core (cpu0-3) frequencies
    local pcore_max=0
    local ecore_max=0
    for i in 0 1 2 3; do
        local freq=$(cat /sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq 2>/dev/null || echo "0")
        if [ "$freq" -gt "$ecore_max" ] 2>/dev/null; then ecore_max=$freq; fi
    done
    for i in 4 5 6 7; do
        local freq=$(cat /sys/devices/system/cpu/cpu${i}/cpufreq/scaling_cur_freq 2>/dev/null || echo "0")
        if [ "$freq" -gt "$pcore_max" ] 2>/dev/null; then pcore_max=$freq; fi
    done
    echo "${ecore_max} ${pcore_max}"
}

get_gpu_stats() {
    nvidia-smi --query-gpu=clocks.current.sm,clocks.current.memory,temperature.gpu,power.draw,utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1
}

get_page_faults() {
    local pid=$1
    local stat=$(cat /proc/$pid/stat 2>/dev/null || echo "")
    if [ -n "$stat" ]; then
        local fields=($stat)
        echo "${fields[9]} ${fields[11]}"  # minflt majflt
    else
        echo "0 0"
    fi
}

wait_server() {
    local max_wait=60
    local i=0
    while [ $i -lt $max_wait ]; do
        if curl -sf http://127.0.0.1:$PORT/health >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        i=$((i+2))
    done
    return 1
}

# ── main ─────────────────────────────────────────────────────────────
echo "=== Proper Benchmark: EHS-25, $RUNS runs, $GEN_TOKENS tokens each ==="
echo "Prompt: $PROMPT"
echo ""

# Ensure port is free
sudo systemctl stop llama-cpp-server.service 2>/dev/null || true
sleep 3

# Output files
echo "run,config,tokens,elapsed_ms,ms_per_token,tok_per_sec,vram_mb,minfaults,majfaults,ecore_mhz,pcore_mhz,gpu_sm_mhz,gpu_temp,gpu_power,gpu_util" > /tmp/proper-bench.csv

for run in $(seq 1 $RUNS); do
    echo "--- Run $run/$RUNS ---"
    
    # Start server
    setsid $LLAMA_BIN \
        -m "$MODEL" --mmproj "$MMPROJ" \
        --host 0.0.0.0 --port $PORT \
        -c 8192 -t 8 -b 512 -ub 512 -ngl 45 \
        -fa on -ctk q4_0 -ctv q4_0 \
        -ehs 25 --split-mode layer \
        --parallel 1 --jinja \
        </dev/null >/tmp/llama-proper.log 2>&1 &
    
    server_pid=$!
    
    if ! wait_server; then
        echo "  FAILED: server didn't start"
        kill -9 $server_pid 2>/dev/null || true
        continue
    fi
    
    # Record initial page faults
    read start_min start_maj <<< $(get_page_faults $server_pid)
    
    # Warmup (50 tokens)
    curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"qwen\",\"messages\":[{\"role\":\"user\",\"content\":\"Hi\"}],\"max_tokens\":50,\"temperature\":0}" \
        >/dev/null 2>&1
    
    # Record clocks BEFORE benchmark
    read ecore_before pcore_before <<< $(get_cpu_freq)
    gpu_before=$(get_gpu_stats)
    
    # Start background clock monitor (sample every 0.5s)
    (
        while kill -0 $server_pid 2>/dev/null; do
            read ecore pcore <<< $(get_cpu_freq)
            gpu=$(get_gpu_stats)
            echo "$(date +%s%N),$ecore,$pcore,$gpu" >> /tmp/clock-monitor-$run.csv
            sleep 0.5
        done
    ) &
    monitor_pid=$!
    
    # Benchmark: timed generation
    start_ns=$(date +%s%N)
    response=$(curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"qwen\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}],\"max_tokens\":$GEN_TOKENS,\"temperature\":0}" 2>/dev/null)
    end_ns=$(date +%s%N)
    
    elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
    
    # Extract completion tokens
    completion_tokens=$(echo "$response" | grep -o '"completion_tokens":[0-9]*' | cut -d: -f2 || echo "$GEN_TOKENS")
    
    # Record final page faults
    read end_min end_maj <<< $(get_page_faults $server_pid)
    minfaults=$((end_min - start_min))
    majfaults=$((end_maj - start_maj))
    
    # Record VRAM
    vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
    
    # Stop monitor
    kill $monitor_pid 2>/dev/null || true
    wait $monitor_pid 2>/dev/null || true
    
    # Calculate metrics
    if [ "$elapsed_ms" -gt 0 ] && [ "$completion_tokens" -gt 0 ] 2>/dev/null; then
        tok_per_sec=$(echo "scale=2; $completion_tokens * 1000 / $elapsed_ms" | bc 2>/dev/null || echo "0")
        ms_per_token=$(echo "scale=2; $elapsed_ms / $completion_tokens" | bc 2>/dev/null || echo "0")
    else
        tok_per_sec=0
        ms_per_token=0
    fi
    
    # Get average clocks from monitor
    if [ -f /tmp/clock-monitor-$run.csv ]; then
        avg_ecore=$(awk -F, '{sum+=$2; n++} END {if(n>0) printf "%.0f", sum/n; else print "0"}' /tmp/clock-monitor-$run.csv)
        avg_pcore=$(awk -F, '{sum+=$3; n++} END {if(n>0) printf "%.0f", sum/n; else print "0"}' /tmp/clock-monitor-$run.csv)
        avg_gpu_sm=$(awk -F, '{sum+=$4; n++} END {if(n>0) printf "%.0f", sum/n; else print "0"}' /tmp/clock-monitor-$run.csv)
        avg_gpu_temp=$(awk -F, '{sum+=$6; n++} END {if(n>0) printf "%.0f", sum/n; else print "0"}' /tmp/clock-monitor-$run.csv)
        avg_gpu_power=$(awk -F, '{sum+=$7; n++} END {if(n>0) printf "%.1f", sum/n; else print "0"}' /tmp/clock-monitor-$run.csv)
        avg_gpu_util=$(awk -F, '{sum+=$8; n++} END {if(n>0) printf "%.0f", sum/n; else print "0"}' /tmp/clock-monitor-$run.csv)
    else
        avg_ecore=0; avg_pcore=0; avg_gpu_sm=0; avg_gpu_temp=0; avg_gpu_power=0; avg_gpu_util=0
    fi
    
    # Log to CSV
    echo "$run,ehs25,$completion_tokens,$elapsed_ms,$ms_per_token,$tok_per_sec,$vram,$minfaults,$majfaults,$avg_ecore,$avg_pcore,$avg_gpu_sm,$avg_gpu_temp,$avg_gpu_power,$avg_gpu_util" >> /tmp/proper-bench.csv
    
    echo "  $completion_tokens tokens in $elapsed_ms ms = $tok_per_sec tok/s, $ms_per_token ms/tok"
    echo "  faults: minor=$minfaults major=$majfaults"
    echo "  clocks: ecore=${avg_ecore}MHz pcore=${avg_pcore}MHz gpu_sm=${avg_gpu_sm}MHz gpu_temp=${avg_gpu_temp}°C"
    
    # Kill server and wait for cooldown
    kill $server_pid 2>/dev/null || true
    wait $server_pid 2>/dev/null || true
    sleep 5  # cooldown between runs
done

echo ""
echo "=== STATISTICAL SUMMARY ==="
# Calculate statistics from CSV
awk -F, 'NR>1 {
    sum+=$5; sumsq+=$5*$5; n++
    if(n==1 || $5<min) min=$5
    if(n==1 || $5>max) max=$5
    vals[n]=$5
    sum_ecore+=$10; sum_pcore+=$11; sum_gpu+=$12; sum_temp+=$13
}
END {
    if(n>0) {
        mean=sum/n
        stddev=sqrt(sumsq/n - mean*mean)
        # Sort for median
        for(i=1;i<=n;i++) for(j=i+1;j<=n;j++) if(vals[i]>vals[j]) {t=vals[i];vals[i]=vals[j];vals[j]=t}
        median=vals[int(n/2)+1]
        p90=vals[int(n*0.9)+1]
        
        printf "Runs: %d\n", n
        printf "ms/token: min=%.1f max=%.1f mean=%.1f median=%.1f P90=%.1f stddev=%.1f\n", min, max, mean, median, p90, stddev
        printf "tok/s: %.2f\n", 1000/mean
        printf "CPU: ecore_avg=%.0fMHz pcore_avg=%.0fMHz\n", sum_ecore/n, sum_pcore/n
        printf "GPU: sm_avg=%.0fMHz temp_avg=%.0f°C\n", sum_gpu/n, sum_temp/n
    }
}' /tmp/proper-bench.csv

echo ""
echo "=== RAW DATA ==="
cat /tmp/proper-bench.csv | column -t -s,

# Restart normal service
sudo systemctl start llama-cpp-server.service 2>/dev/null || true
echo ""
echo "=== DONE ==="
