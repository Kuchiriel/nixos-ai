# Harvest 4 newest codacus (@general subagent)

- **sessão:** `ses_f2e9950acffeEWCJCo7QzmWrwV`
- **quando:** 2026-09-24 03:12 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 12 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Read 4 YouTube transcripts (.en.vtt in /home/nixos/Books/codacus-transcripts/) for videos IH8XmxiwliQ, Tffg78mOgAk, 8F_5pdcD3HY, g_JG1Xbnz0g. Extract only tricks improving local LLM inference on RTX 4050 6GB + llama-server (Qwen3/Bonsai). Append EXACTLY 4 sections (in this order) to /home/nixos/Books/codacus/FINDINGS.md using format:
## <id> | <title>
- trick: <one line or NONE>
- flags: <exact flags or NONE>
- gain: <numbers or qualitative>
- priority: <P0/P1/P2>
Be terse. Nothing else needed.

---

## · ?

Grabbing 4 transcripts to mine RTX 4050 wins.

---

## · ?

Found the files — now stripping timestamps to surface the inference tricks.

---

## · ?

I've got what I need — appending the 4 findings in order.

---

## · ?

Done. Appended exactly 4 sections in order (IH8XmxiwliQ P1, Tffg78mOgAk P2, 8F_5pdcD3HY P0, g_JG1Xbnz0g P2) to FINDINGS.md.

Key hit: 8F_5pdcD3HY — `--n-cpu-moe` + `--no-mmap` + `--mlock` + TurboQuant KV = 3→17 tok/s, 64K→256K ctx on 6GB; speculative decoding hurts MoE+SSM (17→11).

---

