# Harvest codacus remainder 28 (@general subagent)

- **sessão:** `ses_f2e9ede6effe4kWlYPkrjAekwr`
- **quando:** 2026-09-24 03:06 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 8 (exportadas: 7)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

You are harvesting YouTube transcripts for APPLICABLE PERFORMANCE TRICKS. Read these Codacus videos and extract only what can improve local LLM inference on an RTX 4050 6GB VRAM + 32GB RAM Linux box running llama-server (llama.cpp) with Qwen3/Bonsai models.

Video IDs in order (read the .en.vtt for each in /home/nixos/Books/codacus-transcripts/):
3DYhAAXIneQ 5J3A3Zm5Ktc 7B2dMUy7b1U 7qJgo8do-9c 9q1RexwBQI0 9vY4-Z-tkHs B7srKBls2iA CRiLWV9wx9Y EYAffT90ATU GToxHK6QQbc KSQ4Bv8k0K4 Li35SosSLXg NdYHRl1J_nY QP2crFSYTT0 RN1fClJW93U XfDfmjlvvf8 Ym503n8lFBQ cY2ZZICGelI hFJOZSrwGKc hjZZSSNpIuo k0rncpQYKhI qonGjDAF_a8 s7xzRySvaOY t67C2WeDNvI tgmw-wI-zr8 wqD_406iu_o xFEcAGB5kyg ykYnCBFV1dQ

For EACH video with a transcript file present, write EXACTLY one section to /home/nixos/Books/codacus/FINDINGS-part3.md (create/append; you own this file):
## <id> | <title>
- trick: <one-line applicable trick or NONE>
- flags: <exact llama-server/llama.cpp flags or commands, or NONE>
- gain: <expected gain with numbers from video or qualitative>
- priority: <P0/P1/P2 for RTX4050-6GB>
Skip videos without transcript files. Skip non-technical content with trick: NONE and one-line why. No other output needed. Be terse.

---

## · ?

Mining transcripts for RTX 4050-ready inference tricks.

---

## · ?

27 of 28 transcripts found on disk — reading them now.

---

## · ?

All 28 transcripts are present — dumping them for extraction.

---

## · ?

Shorts extracted — pulling full text from the two long-form videos.

---

## · ?

Transcripts digested — grabbing exact titles, then writing the file.

---

## · ?

Wrote `/home/nixos/Books/codacus/FINDINGS-part3.md` — 28 sections (all requested IDs had transcripts, including `9vY4-Z-tkHs`).

Signal for RTX 4050 6GB: **P0** = D-Flash speculative decoding for code-only on fully-resident 8B (`9vY4`), Gemma 4 QAT GGUFs + MoE attention-on-GPU hybrid (`xFEc`); **P1** = tiny distilled function-call sidecar (`7qJgo8do`), VRAM-fit sizing, specialist/hierarchical prompts, streaming, parallel fan-out; rest = NONE (news/opinion) or P2 (blocked on llama.cpp ports: middle-out, MTP drafter, 6x KV compression).

---

