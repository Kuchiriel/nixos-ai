# PLATFORM AUDIT — 2026-08-30

## Context

Based on ChatGPT's deep analysis of the nixos-ai repository, which identified that we were focusing too much on Nightwatch when the platform infrastructure needed attention first.

## Audit Scope

- Flake/NixOS evaluation graph
- Boot/kernel/initrd
- NVIDIA/CUDA/Wayland
- Systemd dependency graph
- Thermal/power management
- llama.cpp profiles and parameters
- VRAM/RAM budgeting
- Home Manager

## Findings

### P0 — Critical Issues

#### 1. Security: PermitRootLogin = "yes" ✅ FIXED

**Before:**
```nix
services.openssh = {
  enable = true;
  settings.PermitRootLogin = "yes";
};
```

**After:**
```nix
services.openssh = {
  enable = true;
  settings.PermitRootLogin = "prohibit-password"; # Segurança: login root só por chave SSH
};
```

**Impact:** Prevents password-based root login over SSH. Root can still login via SSH keys.

#### 2. Systemd Sandboxing ✅ FIXED

**Services hardened:**
- `jarvis-idle-worker`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=512M
- `jarvis-telegram`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=256M
- `nightwatch-timer`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=2G
- `llama-cpp-embeddings`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=512M
- `llama-cpp-rerank`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=256M

**Note:** `llama-cpp-server` cannot be sandboxed because it runs as root and needs GPU access.

### P0 — Kernel Parameters Analysis

#### 1. `intel_idle.max_cstate=1` — ⚠️ REVIEW RECOMMENDED

**Purpose:** Limits CPU C-states to C1, reducing wake latency by 1-3% for decode.

**Pros:**
- Lower wake latency (CPU wakes faster from idle)
- May improve token generation speed slightly

**Cons:**
- Significantly increases power consumption
- Increases heat generation
- May contribute to thermal throttling

**Recommendation:** Consider removing unless freeze issues are observed. The thermal benefits of removing it may outweigh the 1-3% decode improvement.

#### 2. `pcie_aspm=force` — ✅ KEEP

**Purpose:** Forces PCIe Active State Power Management, reducing GPU idle power.

**Pros:**
- Reduces PCIe power consumption by ~40%
- Reduces heat generation from PCIe devices
- Helps with thermal management

**Cons:**
- Can cause system freezes on some hardware
- May cause WiFi disconnections

**Recommendation:** Keep this parameter. The thermal benefits are significant for a laptop with RTX 4050.

#### 3. `preempt=full` — ✅ KEEP

**Purpose:** Full preemption for linuxPackages_zen kernel.

**Analysis:** This is correct for the Zen kernel we're using. The comment in the code says "Preempção total do kernel Zen" which is accurate.

#### 4. `split_lock_detect=off` — ⚠️ REVIEW RECOMMENDED

**Purpose:** Disables penalties for split locks in AI workloads.

**Pros:**
- May improve AI workload performance

**Cons:**
- Hides potential hardware issues
- May cause data corruption in rare cases

**Recommendation:** Test without this parameter to see if AI workloads are affected.

#### 5. `nvme_core.io_timeout=10` — ⚠️ REVIEW RECOMMENDED

**Purpose:** More aggressive NVMe I/O timeout.

**Pros:**
- Faster error recovery

**Cons:**
- May cause data loss on slow I/O operations
- May cause filesystem corruption under heavy load

**Recommendation:** Consider increasing to 30 or removing entirely.

### P1 — llama.cpp Profiles

#### Current Profiles

| Profile | Model | Context | GPU Layers | MoE Flags | Use Case |
|---------|-------|---------|------------|-----------|----------|
| vm | Qwen3-4B | 131072 | 0 | None | Lab/VM |
| host | Qwen3.6-35B-A3B | 32768 | 45 | ncmoe=36 | Main server |
| host-ncmoe35 | Qwen3.6-35B-A3B | 32768 | 45 | ncmoe=35 | Faster variant |
| host-ehs | Qwen3.6-35B-A3B | 8192 | 45 | ehs=25 | Expert Hot Store |
| host-ehs-optimized | Qwen3.6-35B-A3B | 16384 | 45 | ehs=25 | Optimized EHS |

#### Issues Found

1. **Profile resolution at `let` block:** The `prof = pkgs.aiModels.profiles.${profileName};` is evaluated at module evaluation time, which could cause issues with lazy evaluation.

2. **Hardcoded VRAM budget:** The `ncmoe=36` is hardcoded, not calculated based on available VRAM.

3. **No profile for different use cases:** Roo Dev (large context), Chat (throughput), Jarvis (latency), Benchmark (reproducibility) all use the same profile.

#### Recommendations

1. **Create separate profiles for different use cases:**
   - `roo-dev`: Large context (32k+), parallel=2
   - `chat`: Maximum throughput, parallel=1
   - `jarvis`: Low latency, parallel=1
   - `benchmark`: Reproducible settings

2. **Dynamic VRAM budgeting:**
   ```nix
   # Calculate safe ngl based on available VRAM
   availableVram = 6144 - 2400; # Total - model size
   safeNgl = if availableVram > 4000 then 45 else 35;
   ```

### P1 — VRAM/RAM Budgeting

**Current State:**
- RTX 4050: 6GB VRAM
- Qwen3.6-35B-A3B: ~2.4GB model size
- KV Cache: depends on context size
- MoE experts: 36 on CPU, 9 on GPU

**Issues:**
1. No explicit VRAM budget calculation
2. Hardcoded `ncmoe=36` without considering available VRAM
3. No monitoring of actual VRAM usage

**Recommendation:**
```nix
# Create a VRAM budget module
let
  totalVram = 6144; # MB
  modelSize = 2400; # MB
  kvCacheSize = prof.ctxSize * 64 / 1024; # KB per token
  availableForExperts = totalVram - modelSize - kvCacheSize - 500; # 500MB safety
  expertsOnGpu = builtins.floor (availableForExperts / 100); # ~100MB per expert
in {
  gpuLayers = 45;
  moeFlags = "--n-cpu-moe ${toString (36 - expertsOnGpu)}";
}
```

### P1 — Systemd Dependency Graph

**Current State:**
```
jarvis.target
├── llama-cpp-server.service
│   └── after: network-online.target, qdrant.service
├── llama-cpp-embeddings.service
├── llama-cpp-rerank.service
├── qdrant.service
├── jarvis-idle-worker.service (user)
├── jarvis-telegram.service
└── nightwatch.timer
```

**Issues:**
1. No explicit dependency chain between services
2. No resource limits for most services
3. No sandboxing for llama-cpp-server

**Recommendation:**
```nix
# Add explicit dependencies
llama-cpp-server = {
  after = ["qdrant.service" "network-online.target"];
  requires = ["qdrant.service"];
  # Resource limits
  memoryMax = "8G";
  cpuWeight = 100;
};
```

### P1 — Home Manager

**Current State:**
- Complex module structure with many imports
- Inline scripts in some modules
- Generated files

**Issues:**
1. May be becoming a parallel OS
2. Some configurations duplicated between NixOS and Home Manager
3. Some paths may not be declarative

**Recommendation:**
- Audit all `home.file` and `xdg.configFile` usage
- Ensure all configurations are declarative
- Remove any inline scripts that could be replaced with packages

## Commits

```
f2ab9d2 fix(platform): security hardening + Systemd sandboxing
```

## Next Steps

1. **Test kernel parameter changes** — Remove `intel_idle.max_cstate=1` and monitor thermal behavior
2. **Create llama.cpp profiles** — Separate profiles for Roo Dev, Chat, Jarvis, Benchmark
3. **Implement dynamic VRAM budgeting** — Calculate ngl/ncmoe based on available VRAM
4. **Add explicit Systemd dependencies** — Ensure proper service ordering
5. **Audit Home Manager** — Ensure all configurations are declarative

## Validation

- [x] Security fix applied (PermitRootLogin)
- [x] Systemd sandboxing added to 5 services
- [ ] Kernel parameter changes tested
- [ ] llama.cpp profiles created
- [ ] VRAM budgeting implemented
- [ ] Systemd dependencies verified
- [ ] Home Manager audited

---
**Ver também:** [[../HANDOFF]] | [[../AGENTS.md]] | [[../README]]
