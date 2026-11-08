# Harvest codacus oldest 18 (@general subagent)

- **sessão:** `ses_f2ea0ecfcffeKwN0qok2jRlWx1`
- **quando:** 2026-09-24 03:04 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 12 (exportadas: 6)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

You are harvesting YouTube transcripts for APPLICABLE PERFORMANCE TRICKS. Read the OLDEST Codacus videos and extract only what can improve local LLM inference on an RTX 4050 6GB VRAM + 32GB RAM Linux box running llama-server (llama.cpp) with Qwen3/Bonsai models.

Video IDs oldest-first (read the .en.vtt for each in /home/nixos/Books/codacus-transcripts/):
DxznNEC4GXw 9NfMNdqBKxE PGulmfQCfNQ bSgJDSUI4nY mWLjk2ODg_I w4QJnrVU4zc Oq0UdRy1LcM Xuh6PzhqrgQ akXT0DRvvK4 3mX_dc9ZNRA WkLdJ_1TKdY g_JG1Xbnz0g 8F_5pdcD3HY Tffg78mOgAk 9vY4-Z-tkHs kpMLDIj6Ls8

For EACH video with a transcript file present, write EXACTLY one section to /home/nixos/Books/codacus/FINDINGS-part1.md (create/append; you own this file):
## <id> | <title>
- trick: <one-line applicable trick or NONE>
- flags: <exact llama-server/llama.cpp flags or commands, or NONE>
- gain: <expected gain with numbers from video or qualitative>
- priority: <P0/P1/P2 for RTX4050-6GB>
Skip videos without transcript files. Skip non-technical content (opinion/news) with trick: NONE and one-line why. No other output needed. Be terse.

---

## · ?

Harvesting Codacus transcripts for RTX 4050 tricks — reading oldest first.

---

## · ?

The project-scoped reader is blocked — switching to the filesystem reader.

---

## · ?

First six are mostly homelab philosophy — extracting the rest with plain-text stripping to find real inference flags.

---

## · ?

All twelve transcripts stripped — now writing the findings file.

---

## · ?

Wrote 12 sections to `/home/nixos/Books/codacus/FINDINGS-part1.md`. Skipped 4 IDs with no transcript files (g_JG1Xbnz0g, 8F_5pdcD3HY, Tffg78mOgAk, 9vY4-Z-tkHs). P0s: kpMLDIj6Ls8 (MTP +23% on 6GB offload, +65% dense) and Oq0UdRy1LcM (KV-cache quant, 4.4x at 128K).

---

