# llama-cpp service audit (@general subagent)

- **sessão:** `ses_f7e857991ffekUhpo833coogCg`
- **quando:** 2026-09-08 14:44 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 8 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only, NO edits), audit how llama-server is launched and managed. Read modules/services/llama-cpp.nix (or wherever llama-server services are defined) fully, plus any systemd service definitions for LLM/embed/rerank, wrapper scripts (llama-prism-wrapper, llama-wackmall-wrapper), port assignments, GPU/VRAM env (CUDA_VISIBLE_DEVICES, n-gpu-layers), health checks, restart policy, model file resolution (how pkgs.aiModels profiles map to store paths), and how the "active profile" is chosen (which profile serves :8080 now — bonsai? host? fast?). Also check hosts/nitro-v15/ for overrides and scripts/ for model-related scripts. Return: exact file paths, ports, how to switch the served model today (what command/rebuild), what would be needed to serve TWO models, any existing multi-instance support. Max 80 lines, file:line evidence. Do NOT change anything.

---

## · ?

Auditing llama-server launch — read-only, no changes.

---

## · ?

Found main server on bonsai — now tracing wrappers, model store, and health checks.

---

## · ?

Wrappers and model mapping traced — final check for multi-instance support.

---

## · ?

Audit (read-only, no changes):

**Services — `modules/services/llama-cpp.nix`:**
1. `llama-cpp.nix:94,100` single `systemd.services.llama-cpp-server`, `wantedBy=[jarvis.target multi-user.target]`, `partOf=[jarvis.target]`
2. `llama-cpp.nix:28-29` main port `8080`; `:75-77` embeddings `8081`; `:82-83` rerank `8082`
3. `llama-cpp.nix:63-65` `bindAddress=127.0.0.1`; embed/rerank hardcode `--host 127.0.0.1` (`:139,:168`); `hosts/nitro-v15/configuration.nix:233` firewall `22,8080,8081,4000`
4. `llama-cpp.nix:8,10` `profileName=config.services.llama-cpp-server.profile`, `prof=pkgs.aiModels.profiles.${profileName}` — single-slot, no multi-instance
5. `llama-cpp.nix:15,20-22` `llamaCppPkg=pkgs.llama-cpp.override{cudaSupport=true}` else `../ai/${prof.wrapper}.sh` if `prof.wrapper!=null`
6. `llama-cpp.nix:108-116` `script: exec ${llamaBin} -m <model> [--mmproj] --host --port -c -t -b -ub [-ngl] +kvCache+moeFlags+extraArgs`
7. `llama-cpp.nix:104-106` `LD_LIBRARY_PATH` only for wrapper profiles (prism/wackmall): `prism-bin/...:cc.lib:openssl:cuda_cudart:libcublas:/run/opengl-driver/lib`
8. `modules/ai/llama-prism-wrapper.sh:5` `exec /home/nixos/projects/prism-bin/llama-prism-b10660-e311ed3/llama-server "$@"` (impure, outside store)
9. `modules/ai/llama-wackmall-wrapper.sh:4-5` `LD_LIBRARY_PATH=/run/opengl-driver/lib`, `exec .../llama-wackmall/build/bin/llama-server`
10. `llama-cpp.nix:122,144` main+embed `Restart=on-failure` (no `RestartSec`); `:171-181` rerank has NO `Restart` (sandbox+`MemoryMax=1G,TasksMax=64`); embed `:153-154` `MemoryMax=2G,TasksMax=32` + `ProtectSystem=strict,PrivateTmp,NoNewPrivileges`
11. `llama-cpp.nix:164` only GPU env is rerank `CUDA_VISIBLE_DEVICES=""` (CPU-force); no `CUDA_VISIBLE_DEVICES` on main/embed; `-ngl` omitted if `gpuLayers==0` (`:113`)
12. No `ExecStartPre`/`healthcheck` in-unit (grep `health|ExecStartPre|RestartSec` in `modules/services/` hits only webui/watchdog/heal, zero in `llama-cpp.nix`); health is external: `BUFFY.md:44-46` `curl 127.0.0.1:8080|8081|8082/health`, `ga_engine.py:328` / `scripts/ncmoe-sweep.py:147` `curl -sf .../health`

**Models — `modules/ai/models.nix` + `flake.nix`:**
13. `flake.nix:42` `aiModels=callPackage ./modules/ai/models.nix{}`; `:49-58` overlay `llama-cpp` from unstable + `cudaSupport=true`; `:102` `inherit aiModels` → `pkgs.aiModels`
14. `llama-cpp.nix:110-111` resolution: `-m "${pkgs.aiModels.${prof.model}}"` (+`--mmproj "${pkgs.aiModels.${prof.mmproj}}"`), i.e. `fetchurl` store path; e.g. `models.nix:91-94` `llm-bonsai`=prism-ml Q2_0_g64, `:76-79` `llm-host`=Qwen3.6-35B MoE, `:82-85` mmproj, `:97-100` embed nomic-moe Q8_0, `:104-107` reranker bge Q4_K_M
15. `models.nix:48-51` `hostBase{gpuLayers=45,model=llm-host,mmproj=llm-host-mmproj,kvCache=-fa on...}`; `:287-306` `bonsai{model=llm-bonsai,mmproj=null,ngl=99,ctx32K,t8,b2048,ub512,wrapper=llama-prism-wrapper}`; `:420-435` `fast{ngl=25,ctx4096,t8,mmproj=null}`; `:311-335` `host{ctx32K,...}`

**Active profile:**
16. `hosts/nitro-v15/configuration.nix:155-158` `services.llama-cpp-server.profile="bonsai"` + embed/rerank `enable=true` → `:8080`=Bonsai-8B now, NOT `host`/`fast`; default fallback `llama-cpp.nix:36-39` `jarvis.environment==host?"host":"vm"`, overridden here

**Switch model today:**
17. Edit `hosts/nitro-v15/configuration.nix:156` to `"host"|"host-ncmoe35"|"host-ehs"|"fast"|"bonsai"|...` (enum `llama-cpp.nix:32-35`), then `rebuild-host.sh:52` `nh os switch ... -H nitro-v15` (validates via `scripts/nix-validate.sh`, `git add -A`+commit since flakes see only index)

**Two models / multi-instance:** none exists (`default.nix:16` imports single `llama-cpp.nix`). Need: clone `systemd.services.llama-cpp-server` → e.g. `llama-cpp-server-2` with own `port` (8083/8091), own `profile`, `wantedBy jarvis.target`, firewall+litellm/WebUI routing; blocker: RTX4050 6GB budget (`AGENTS.md` main ~4.6GB; `models.nix:34-37` 6144-2400-500) — Qwen35B+Bonsai simultaneous OOM; viable pairs only small ctx / CPU-offload or time-share.

---

