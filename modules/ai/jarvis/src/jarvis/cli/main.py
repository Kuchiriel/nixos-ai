"""CLI do JARVIS.

Subcomandos:
  jarvis intent "texto"          — classifica a intenção (determinístico)
  jarvis status                  — verifica disponibilidade de llama.cpp e Qdrant
  jarvis chat "pergunta"         — resposta via llama.cpp (OpenAI-compat)
  jarvis rag "busca"             — busca híbrida (dense + sparse BM25 + boosts V4.0.5)
  jarvis index <dir>             — indexa um diretório de código no Qdrant
  jarvis migrate <legacy-dir>    — migração one-shot do índice .ai-index legado
  jarvis parity <legacy-dir>     — teste de paridade (top-k legado vs novo)
  jarvis doctor                  — diagnóstico de saúde de todos os serviços
  jarvis metrics                 — métricas e telemetria dos logs JSONL
  jarvis agent "tarefa"         — agente tool-calling (allowlist + aprovação + audit)
  jarvis ask "pedido"           — roteador: doctor/nixos/rag/agent (caminho mais barato)
  jarvis remember "fato"        — grava um evento na memória episódica
  jarvis recall "busca"         — recupera eventos da memória (híbrido)
  jarvis lessons "erro"         — lições passadas relevantes (estilo experience_buffer)
  jarvis hwdetect               — detecta o hardware (RAM/VRAM/CPU/GPU/NPU)
  jarvis hwprofile              — calcula flags SOTA + melhor modelo p/ o hardware
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from jarvis.core.config import get_config
from jarvis.core.intents import classify_intent


def _cmd_status(_args: argparse.Namespace) -> int:
    from jarvis.providers.llm import LLMClient
    from jarvis.providers.vector_store import QdrantStore

    cfg = get_config()
    llm = LLMClient(cfg)
    store = QdrantStore(cfg)
    print(json.dumps({
        "llama_cpp": llm.is_available(),
        "qdrant": store.is_available(),
        "state_dir": str(cfg.ensure_state_dir()),
    }, indent=2))
    return 0


def _cmd_intent(args: argparse.Namespace) -> int:
    print(classify_intent(args.text))
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    from jarvis.providers.llm import LLMClient

    llm = LLMClient(get_config())
    response = llm.chat([{"role": "user", "content": args.text}])
    print(response)
    return 0


def _cmd_rag(args: argparse.Namespace) -> int:
    from jarvis.core.rag import HybridSearch

    cfg = get_config()
    search = HybridSearch(cfg)
    hits = search.search(args.query, top_k=args.top_k)
    out = []
    for hit in hits:
        out.append({
            "path": hit.path,
            "score": round(hit.score, 4),
            "symbols": hit.payload.get("symbols", []),
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    from jarvis.core.rag import HybridIndexer

    indexer = HybridIndexer(get_config())
    total = indexer.index_directory(args.directory)
    print(json.dumps({"indexed": total}, indent=2))
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    from jarvis.core.legacy_index import load_legacy_index, migrate

    index = load_legacy_index(args.legacy_dir)
    total = migrate(index, get_config())
    print(json.dumps({
        "legacy_index": str(index.index_dir),
        "docs": len(index),
        "migrated_points": total,
    }, indent=2))
    return 0


def _cmd_parity(args: argparse.Namespace) -> int:
    from jarvis.core.legacy_index import load_legacy_index, parity_report

    index = load_legacy_index(args.legacy_dir)
    report = parity_report(index, get_config(), queries=args.queries, top_k=args.top_k)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = report["total_queries"] > 0 and report["overlap_medio"] >= 0.8
    print(f"\n# paridade {'OK' if ok else 'FALHOU'} (overlap médio {report['overlap_medio']})")
    return 0 if ok else 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    from jarvis.core.doctor import doctor_report

    report = doctor_report(get_config())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        overall = report["overall"]
        icon = {"ok": "✅", "degraded": "⚠️", "down": "❌"}.get(overall, "?")
        print(f"{icon} Overall: {overall}")
        for c in report["checks"]:
            mark = {"ok": "✓", "degraded": "⚠", "down": "✗"}.get(c["status"], "?")
            detail = c.get("detail", "")[:60]
            print(f"  {mark} {c['name']:<24} {c['status']:<10} {detail}")
    return 0 if report["overall"] != "down" else 1


def _cmd_metrics(args: argparse.Namespace) -> int:
    from jarvis.core.logging import compute_metrics, read_events

    since_ts = None
    if args.since:
        since_ts = time.time() - (args.since * 3600)
    events = read_events(args.module, since_ts=since_ts, limit=args.limit)
    metrics = compute_metrics(events)
    metrics["log_dir"] = str(_log_dir())
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(f"📊 Métricas — {metrics['total_events']} eventos")
        print(f"   Log dir: {metrics['log_dir']}")
        print()
        if metrics["by_module"]:
            print("Por módulo:")
            for mod, count in sorted(metrics["by_module"].items(), key=lambda x: -x[1]):
                print(f"  {mod:<16} {count}")
        print()
        if metrics["by_level"]:
            print("Por nível:")
            for lvl, count in metrics["by_level"].items():
                if count:
                    print(f"  {lvl:<16} {count}")
        print()
        if metrics["by_event"]:
            print("Por evento:")
            for evt, count in sorted(metrics["by_event"].items(), key=lambda x: -x[1]):
                print(f"  {evt:<24} {count}")
    return 0


def _log_dir():
    from pathlib import Path
    import os
    base = os.environ.get("JARVIS_STATE_DIR", "")
    if base:
        return Path(base).expanduser() / "logs"
    return Path.home() / ".local" / "state" / "jarvis" / "logs"


def _cmd_remember(args: argparse.Namespace) -> int:
    from jarvis.core.memory import EpisodicMemory, KIND_FACT, KIND_LESSON, MemoryEvent

    mem = EpisodicMemory(get_config())
    if args.kind == "lesson":
        event = MemoryEvent(
            kind=KIND_LESSON, text=args.text,
            task=args.task or "", error_pattern=args.error or "", fix=args.fix or "",
        )
    else:
        event = MemoryEvent(kind=KIND_FACT, text=args.text)
    point_id = mem.remember(event)
    print(json.dumps({"remembered": point_id is not None, "id": point_id, "kind": event.kind}, indent=2))
    return 0 if point_id is not None else 1


def _cmd_recall(args: argparse.Namespace) -> int:
    from jarvis.core.memory import EpisodicMemory

    mem = EpisodicMemory(get_config())
    hits = mem.recall(args.query, top_k=args.top_k)
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    return 0


def _cmd_lessons(args: argparse.Namespace) -> int:
    from jarvis.core.memory import EpisodicMemory

    mem = EpisodicMemory(get_config())
    out = mem.lessons(args.query, top_k=args.top_k)
    print(out if out else "(sem lições relevantes)")
    return 0


def _cmd_vault_summarize(args: argparse.Namespace) -> int:
    from jarvis.core.vault import MemoryVault

    result = MemoryVault().summarize(args.since, commit=not args.no_commit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result.get("written"):
        print(f"(nada a resumir: {result.get('reason')})")
        return 1 if str(result.get("reason", "")).startswith("llm_error") else 0
    return 0


def _cmd_vault_list(args: argparse.Namespace) -> int:
    from jarvis.core.vault import MemoryVault

    notes = MemoryVault().list_notes()
    if not notes:
        print("(vault vazio — rode `jarvis vault summarize`)")
        return 0
    for n in notes:
        print(n)
    return 0


def _cmd_telegram(args: argparse.Namespace) -> int:
    """Roda o canal Telegram (long-polling). Exige token + chat_id no env."""
    from jarvis.providers.telegram import TelegramError, TelegramBot, make_channel

    cfg = get_config()
    channel = make_channel(cfg)
    if channel is None:
        # Sai limpo (exit 0) para o systemd não reiniciar em loop: o serviço
        # fica parado até o token ser configurado (EnvironmentFile com `-`).
        print("Telegram não configurado: defina JARVIS_TELEGRAM_TOKEN e "
              "JARVIS_TELEGRAM_CHAT_ID (ex: via /etc/jarvis-telegram.env).",
              file=sys.stderr)
        return 0
    try:
        me = channel._bot.get_me()
        print(f"Bot @{me.get('username', '?')} conectado — polling em "
              f"{cfg.telegram_chat_id} (Ctrl+C para parar)", file=sys.stderr)
    except TelegramError as exc:
        print(f"Falha ao conectar: {exc}", file=sys.stderr)
        return 1
    try:
        channel.run(poll_timeout=args.poll_timeout)
    except KeyboardInterrupt:
        return 0
    return 0


def _cmd_handoff(args: argparse.Namespace) -> int:
    """Gera o pacote de contexto para colar em IAs web (Gemini/ChatGPT).

    Junta AGENTS.md (premissas + perfil) + git log/status + estado das fases
    num único bloco markdown — a IA web começa com as mesmas premissas que
    os agentes locais, sem você digitar nada.
    """
    import subprocess

    # Detecta a raiz do repo pelo CWD (o usuário roda no repo; no build Nix o
    # __file__ aponta para o store, sem AGENTS.md)
    root = Path.cwd()
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
        if top:
            root = Path(top)
    except (OSError, subprocess.SubprocessError):
        pass
    parts: list[str] = []

    if not args.prompt_only:
        agents = root / "AGENTS.md"
        if agents.exists():
            parts.append(f"<!-- AGENTS.md (premissas do repo) -->\n{agents.read_text(encoding='utf-8')}")

        try:
            log = subprocess.run(
                ["git", "-C", str(root), "log", "--oneline", "-8"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--short"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            log, status = "", ""

        if log or status:
            parts.append(
                f"<!-- Estado do repo -->\n"
                f"Últimos commits:\n```\n{log or '(vazio)'}\n```\n"
                f"Árvore de trabalho:\n```\n{status or '(limpa)'}\n```"
            )

    if args.task:
        parts.append(f"<!-- Tarefa solicitada -->\nTAREFA: {args.task}")
    else:
        parts.append("<!-- Tarefa solicitada -->\nTAREFA: (descreva aqui o que você quer que a IA web faça)")

    print("\n\n---\n\n".join(parts))
    return 0


def _cmd_idle_status(args: argparse.Namespace) -> int:
    """Mostra o estado do modo idle: carga, IdleHint e próximas tarefas."""
    from jarvis.core.idle import IdleWorker, is_idle, user_is_idle

    worker = IdleWorker()
    due = worker.due_tasks()
    out = {
        "idle": is_idle(max_load=args.max_load),
        "carga_1min": round(__import__("os").getloadavg()[0], 2),
        "max_load": args.max_load,
        "logind_idle": user_is_idle(),
        "tarefas_devidas": [t.name for t in due],
        "heartbeats": {},
    }
    for task in worker._tasks:
        last = worker._last_run(task.name)
        out["heartbeats"][task.name] = {
            "ultimo_run": round(last, 1) if last else None,
            "intervalo_min": task.min_interval_min,
        }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_idle_worker(args: argparse.Namespace) -> int:
    """Executa no máximo uma tarefa de self-knowledge (chamado pelo timer)."""
    from jarvis.core.idle import IdleWorker

    result = IdleWorker().run_once(
        force=args.force, max_load=args.max_load, idle_check=not args.no_idle_check,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ran") else 1


def _cmd_ask(args: argparse.Namespace) -> int:
    from jarvis.core.feedback import notify, set_status
    from jarvis.core.router import (
        handle_agent, handle_doctor, handle_fastpath, handle_nixos, handle_rag, route_request,
    )

    cfg = get_config()
    route = route_request(args.prompt)
    set_status("thinking", f"rota: {route.handler} — {args.prompt[:40]}")
    try:
        if route.handler == "fastpath":
            out = handle_fastpath(route.query)
        elif route.handler == "doctor":
            out = handle_doctor(cfg)
        elif route.handler == "nixos":
            out = handle_nixos(route.query, cfg)
        elif route.handler == "rag":
            out = handle_rag(route.query, cfg, top_k=args.top_k)
        else:
            out = handle_agent(route.query, cfg, approve=args.approve)
    except Exception as exc:  # noqa: BLE001
        set_status("error", str(exc)[:120])
        notify("JARVIS", f"Erro: {exc}", urgency="critical")
        raise
    out["_route"] = {"handler": route.handler, "reason": route.reason}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    set_status("done", f"rota {route.handler} concluída")
    return 0


def _cmd_agent(args: argparse.Namespace) -> int:
    import shutil

    from jarvis.core.agent import Agent

    cfg = get_config()
    state = cfg.ensure_state_dir()
    mcp_servers = {}
    for spec in args.mcp:
        if "=" in spec:
            name, _, cmd = spec.partition("=")
            mcp_servers[name.strip()] = cmd.strip()
        else:
            mcp_servers[spec.strip()] = spec.strip()
    # Default: mcp-nixos se disponível no PATH (vem do package Nix)
    if not mcp_servers and shutil.which(cfg.mcp_nixos_bin):
        mcp_servers["nixos"] = cfg.mcp_nixos_bin
    # Memória episódica: injeta PAST LESSONS no prompt (cascade do legado) e
    # grava lições automáticas quando um comando falha. Falhas não quebram o agente.
    memory = None
    try:
        from jarvis.core.memory import EpisodicMemory
        memory = EpisodicMemory(cfg)
    except Exception:  # noqa: BLE001 — sem memória, agente segue normal
        pass
    agent = Agent(
        cfg, approve=args.approve, audit_path=state / "agent-audit.jsonl",
        mcp_servers=mcp_servers, memory=memory,
    )
    result = agent.run(args.prompt)

    print(result.final_response)
    if result.commands_run:
        print(f"\n# comandos executados ({len(result.commands_run)}):")
        for c in result.commands_run:
            print(f"  · {c}")
    if result.commands_denied:
        print(f"\n# comandos negados ({len(result.commands_denied)}):")
        for c in result.commands_denied:
            print(f"  · {c}")
    return 2 if result.commands_denied else 0


def _cmd_benchmark(args: argparse.Namespace) -> int:
    from jarvis.core.benchmark import main_benchmark

    argv = []
    if args.json:
        argv.append("--json")
    if args.top_k:
        argv += ["--top-k", str(args.top_k)]
    return main_benchmark(argv)


def _cmd_emotion(args: argparse.Namespace) -> int:
    from jarvis.core.emotion import main_emotion

    return main_emotion(args.text)


def _cmd_eval_rag(args: argparse.Namespace) -> int:
    from jarvis.core.eval_rag import main_eval_rag

    argv = []
    if args.json:
        argv.append("--json")
    if args.top_k:
        argv += ["--top-k", str(args.top_k)]
    return main_eval_rag(argv)


def _cmd_regression(args: argparse.Namespace) -> int:
    from jarvis.core.regression import main_regression

    argv = []
    if args.save_baseline:
        argv.append("--save-baseline")
    if args.baseline:
        argv += ["--baseline", args.baseline]
    if args.offline:
        argv.append("--offline")
    if args.json:
        argv.append("--json")
    return main_regression(argv)


def _cmd_heal(args: argparse.Namespace) -> int:
    from jarvis.core.heal import main_heal

    argv = []
    if args.watch:
        argv.append("--watch")
    if args.interval:
        argv += ["--interval", str(args.interval)]
    if args.cooldown:
        argv += ["--cooldown", str(args.cooldown)]
    if args.no_alerts:
        argv.append("--no-alerts")
    if args.json:
        argv.append("--json")
    return main_heal(argv)


def _cmd_hwdetect(_args: argparse.Namespace) -> int:
    """Detecta o hardware real e classifica o tier (Termux → datacenter)."""
    from jarvis.core.hwdetect import classify, detect, memory_bandwidth_gb_s

    hw = detect()
    out = {
        "tier": classify(hw),
        "platform": hw.platform,
        "cpu": {"vendor": hw.cpu.vendor, "cores": hw.cpu.cores,
                 "threads": hw.cpu.threads, "freq_ghz": hw.cpu.freq_ghz,
                 "model": hw.cpu.model},
        "ram_gb": round(hw.ram_gb + hw.unified_memory_gb, 1),
        "gpu": {"name": hw.gpu.name, "backend": hw.gpu.backend,
                 "vram_gb": hw.gpu.vram_gb, "count": hw.gpu.count,
                 "compute_cap": hw.gpu.compute_cap},
        "aux_gpu": hw.aux_gpu_name or None,
        "npu": hw.npu_name or None,
        "apple_silicon": hw.is_apple_silicon,
        "termux": hw.is_termux,
        "bandwidth_gb_s": memory_bandwidth_gb_s(hw),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_hwprofile(args: argparse.Namespace) -> int:
    """Calcula flags SOTA do llama.cpp + melhor modelo para ESTE hardware.

    Saída: modelo escolhido, flags (ngl/n-cpu-moe/ctx/KV/fa), comando
    llama-server pronto, previsão de t/s e o bloco models.nix para declarar.
    """
    from jarvis.core.hwdetect import detect
    from jarvis.core.hwprofile import full_report

    hw = detect()
    report = full_report(hw, ctx_target=args.ctx)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    # Saída human-readable
    hw_ = report["hardware"]
    print(f"Tier: {report['tier']}")
    print(f"Hardware: {hw_['cpu']} · {hw_['cores']}c/{hw_['threads']}t · "
          f"RAM {hw_['ram_gb']}GB · GPU {hw_['gpu']} ({hw_['backend']}, "
          f"{hw_['vram_gb']}GB × {hw_['gpus']}) · NPU {hw_['npu']}")
    print(f"Banda de memória estimada: {hw_['bandwidth_gb_s']} GB/s")
    print()
    m = report["modelo"]
    print(f"Melhor modelo: {m['nome']}")
    print(f"  · tamanho GGUF: {m['tamanho_gguf_gb']}GB")
    print(f"  · MoE: {'sim' if m['moe'] else 'não'} · vision: {'sim' if m['vision'] else 'não'}")
    print(f"  · nota: {m['nota']}")
    print()
    f = report["flags"]
    print(f"Flags: -ngl {f['ngl']} · --n-cpu-moe {f['n_cpu_moe']} · -c {f['ctx']} · "
          f"KV {f['kv']} · -fa {'on' if f['fa'] else 'off'} · -t {f['threads']} · "
          f"-ub {f['ubatch']}" + (f" · split {f['split_mode']}" if f['split_mode'] else ""))
    print(f"Offload: {f['offload']} · previsão: ~{report['previsao_tps']} t/s")
    for w in report["avisos"]:
        print(f"  ⚠ {w}")
    print()
    print("Comando (llama-server):")
    # quebra por espaços em linhas de ~96 colunas para legibilidade
    toks, line, out = report["comando"], "  ", []
    for t in toks:
        if len(line) + len(t) + 1 > 96:
            out.append(line.rstrip() + " \\")
            line = "  " + t
        else:
            line += (" " if line.strip() else "") + t
    out.append(line.rstrip())
    print("\n".join(out))
    print()
    print("Bloco models.nix (cole em modules/ai/models.nix → profiles):")
    print(report["models_nix"])
    if report.get("aux_gpu"):
        print()
        print(f"iGPU integrada: {report['aux_gpu']}")
        print("Offload auxiliar recomendado (SYCL/OpenVINO):")
        for r in report.get("aux_recs", []):
            print(f"  · {r['desc']} ({r['backend']})")
    return 0


def _cmd_stt(args: argparse.Namespace) -> int:
    from jarvis.core.voice import main_stt

    return main_stt([args.wav, "--model", args.model])


def _cmd_speak(args: argparse.Namespace) -> int:
    from jarvis.core.voice import main_tts

    argv = [args.text, "--voice", args.voice]
    if args.no_play:
        argv.append("--no-play")
    return main_tts(argv)


def _cmd_voice(args: argparse.Namespace) -> int:
    from jarvis.core.voice import main_voice

    argv = [args.wav, "--model", args.model]
    if args.no_tts:
        argv.append("--no-tts")
    return main_voice(argv)


def _cmd_audiobook(args: argparse.Namespace) -> int:
    from jarvis.core.audiobook import (
        cmd_list, cmd_next, cmd_pause, cmd_prev, cmd_read, cmd_resume,
        cmd_scan, cmd_status, cmd_stop,
    )

    action = args.audiobook_action
    if action == "scan":
        print(cmd_scan())
    elif action == "list":
        print(cmd_list())
    elif action == "read":
        print(cmd_read(args.book or ""))
    elif action == "stop":
        print(cmd_stop())
    elif action == "pause":
        print(cmd_pause())
    elif action == "resume":
        print(cmd_resume())
    elif action == "next":
        print(cmd_next())
    elif action == "prev":
        print(cmd_prev())
    elif action == "status":
        print(cmd_status())
    else:
        print(f"Ação desconhecida: {action}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS — sistema de IA local")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="verifica serviços (llama.cpp, Qdrant)")
    p_status.set_defaults(func=_cmd_status)

    p_intent = sub.add_parser("intent", help="classifica a intenção de um texto")
    p_intent.add_argument("text")
    p_intent.set_defaults(func=_cmd_intent)

    p_chat = sub.add_parser("chat", help="pergunta via llama.cpp")
    p_chat.add_argument("text")
    p_chat.set_defaults(func=_cmd_chat)

    p_rag = sub.add_parser("rag", help="busca híbrida no Qdrant (dense + sparse + boosts)")
    p_rag.add_argument("query")
    p_rag.add_argument("--top-k", type=int, default=5)
    p_rag.set_defaults(func=_cmd_rag)

    p_index = sub.add_parser("index", help="indexa um diretório de código no Qdrant")
    p_index.add_argument("directory")
    p_index.set_defaults(func=_cmd_index)

    p_migrate = sub.add_parser("migrate", help="migra o índice .ai-index legado para o Qdrant")
    p_migrate.add_argument("legacy_dir", help="diretório do índice legado (ex: ~/.ai-index)")
    p_migrate.set_defaults(func=_cmd_migrate)

    p_parity = sub.add_parser("parity", help="teste de paridade top-k (legado vs novo)")
    p_parity.add_argument("legacy_dir", help="diretório do índice legado (ex: ~/.ai-index)")
    p_parity.add_argument("queries", nargs="+", help="fragmentos de path usados como queries")
    p_parity.add_argument("--top-k", type=int, default=5)
    p_parity.set_defaults(func=_cmd_parity)

    p_doctor = sub.add_parser("doctor", help="diagnóstico de saúde de todos os serviços")
    p_doctor.add_argument("--json", action="store_true", help="saída JSON pura")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_metrics = sub.add_parser("metrics", help="métricas e telemetria dos logs JSONL")
    p_metrics.add_argument("--module", default=None, help="filtrar por módulo (agent|heal|fastpath|voice)")
    p_metrics.add_argument("--since", type=int, default=None, help="janela em horas (ex: --since 24)")
    p_metrics.add_argument("--limit", type=int, default=500, help="máximo de eventos (default 500)")
    p_metrics.add_argument("--json", action="store_true", help="saída JSON pura")
    p_metrics.set_defaults(func=_cmd_metrics)

    p_agent = sub.add_parser("agent", help="agente tool-calling (allowlist + aprovação + audit)")
    p_agent.add_argument("prompt", help="tarefa para o agente")
    p_agent.add_argument("--approve", action="store_true", help="permite aprovação humana para comandos com efeito")
    p_agent.add_argument("--mcp", action="append", default=[], metavar="NOME=COMANDO",
                         help="servidor MCP stdio (ex: --mcp nixos='/nix/store/.../bin/mcp-nixos')")
    p_agent.set_defaults(func=_cmd_agent)

    p_ask = sub.add_parser("ask", help="roteador: escolhe o caminho mais barato (doctor/nixos/rag/agent)")
    p_ask.add_argument("prompt", help="pedido em linguagem natural")
    p_ask.add_argument("--top-k", type=int, default=5, help="para a rota rag")
    p_ask.add_argument("--approve", action="store_true", help="para a rota agent: permite comandos com efeito")
    p_ask.set_defaults(func=_cmd_ask)

    p_remember = sub.add_parser("remember", help="grava evento na memória episódica")
    p_remember.add_argument("text", help="o que lembrar")
    p_remember.add_argument("--kind", choices=["fact", "lesson"], default="fact")
    p_remember.add_argument("--task", help="para lessons: a tarefa")
    p_remember.add_argument("--error", help="para lessons: padrão de erro")
    p_remember.add_argument("--fix", help="para lessons: a correção que funcionou")
    p_remember.set_defaults(func=_cmd_remember)

    p_recall = sub.add_parser("recall", help="recupera eventos da memória (busca híbrida)")
    p_recall.add_argument("query")
    p_recall.add_argument("--top-k", type=int, default=5)
    p_recall.set_defaults(func=_cmd_recall)

    p_lessons = sub.add_parser("lessons", help="lições passadas relevantes (estilo experience_buffer)")
    p_lessons.add_argument("query")
    p_lessons.add_argument("--top-k", type=int, default=3)
    p_lessons.set_defaults(func=_cmd_lessons)

    p_vault = sub.add_parser("vault", help="memória de longo prazo (markdown git-syncado — Fase 7)")
    vault_sub = p_vault.add_subparsers(dest="vault_cmd", required=True)
    p_vsum = vault_sub.add_parser("summarize", help="condensa eventos recentes no vault + grava de volta na memória")
    p_vsum.add_argument("--since", type=int, default=7, help="janela em dias (default 7)")
    p_vsum.add_argument("--no-commit", action="store_true", help="não faz commit git do vault")
    p_vsum.set_defaults(func=_cmd_vault_summarize)
    p_vlist = vault_sub.add_parser("list", help="lista as notas do vault")
    p_vlist.set_defaults(func=_cmd_vault_list)

    p_benchmark = sub.add_parser("benchmark", help="mede latência por rota da cascata (fastpath/doctor/nixos/rag/agent)")
    p_benchmark.add_argument("--top-k", type=int, default=5)
    p_benchmark.add_argument("--json", action="store_true", help="saída JSON pura")
    p_benchmark.set_defaults(func=_cmd_benchmark)

    p_eval = sub.add_parser("eval-rag", help="qualidade do retrieval RAG (NDCG/Recall@k vs ground-truth)")
    p_eval.add_argument("--top-k", type=int, default=5)
    p_eval.add_argument("--json", action="store_true", help="saída JSON pura")
    p_eval.set_defaults(func=_cmd_eval_rag)

    p_reg = sub.add_parser("regression", help="regressão benchmark + eval-rag vs baseline (CI)")
    p_reg.add_argument("--save-baseline", action="store_true", help="mede e salva o baseline")
    p_reg.add_argument("--baseline", default=None, help="path do baseline (default: embutido no pacote)")
    p_reg.add_argument("--offline", action="store_true", help="sem serviços (CI/sandbox): fake search + rotas locais")
    p_reg.add_argument("--json", action="store_true", help="saída JSON pura")
    p_reg.set_defaults(func=_cmd_regression)

    p_telegram = sub.add_parser("telegram", help="canal Telegram (Fase 9): aprovação assíncrona do agente")
    p_telegram.add_argument("--poll-timeout", type=int, default=25, help="timeout do long-polling (s)")
    p_telegram.set_defaults(func=_cmd_telegram)

    p_handoff = sub.add_parser("handoff", help="gera o pacote de contexto p/ colar em IAs web (Gemini/ChatGPT)")
    p_handoff.add_argument("--task", default=None, help="a tarefa que você vai pedir à IA web")
    p_handoff.add_argument("--prompt-only", action="store_true",
                           help="não inclui AGENTS.md/git — só o cabeçalho de tarefa (para respostas curtas)")
    p_handoff.set_defaults(func=_cmd_handoff)

    p_idle = sub.add_parser("idle", help="modo idle: self-knowledge quando o sistema está ocioso")
    idle_sub = p_idle.add_subparsers(dest="idle_cmd", required=True)
    p_istat = idle_sub.add_parser("status", help="mostra carga, IdleHint e tarefas devidas")
    p_istat.add_argument("--max-load", type=float, default=2.0, help="teto de carga (1min)")
    p_istat.set_defaults(func=_cmd_idle_status)
    p_iwork = idle_sub.add_parser("worker", help="executa uma tarefa devida (gate de idle)")
    p_iwork.add_argument("--force", default=None, metavar="TAREFA",
                         help="ignora o gate e força a tarefa (benchmark|regression|eval-rag)")
    p_iwork.add_argument("--max-load", type=float, default=2.0)
    p_iwork.add_argument("--no-idle-check", action="store_true", help="não consulta o logind (só carga)")
    p_iwork.set_defaults(func=_cmd_idle_worker)

    p_hwdetect = sub.add_parser("hwdetect", help="detecta o hardware (RAM/VRAM/CPU/GPU/NPU) e classifica o tier")
    p_hwdetect.set_defaults(func=_cmd_hwdetect)

    p_hwprofile = sub.add_parser("hwprofile", help="calcula flags SOTA do llama.cpp + melhor modelo p/ este hardware")
    p_hwprofile.add_argument("--ctx", type=int, default=None, help="contexto alvo em tokens (default: 32K ou nativo)")
    p_hwprofile.add_argument("--json", action="store_true", help="saída JSON pura")
    p_hwprofile.set_defaults(func=_cmd_hwprofile)

    p_heal = sub.add_parser("heal", help="self-heal: detecta serviços down e repara (restart allowlist)")
    p_heal.add_argument("--watch", action="store_true", help="loop contínuo (daemon)")
    p_heal.add_argument("--interval", type=float, default=60.0, help="intervalo do watch em segundos")
    p_heal.add_argument("--cooldown", type=float, default=300.0, help="cooldown entre restarts do mesmo serviço")
    p_heal.add_argument("--no-alerts", action="store_true", help="não notifica o usuário (notify-send/som)")
    p_heal.add_argument("--json", action="store_true", help="saída JSON pura")
    p_heal.set_defaults(func=_cmd_heal)

    p_emotion = sub.add_parser("emotion", help="detecta emoção de um texto (keywords, zero LLM — prosódia do TTS)")
    p_emotion.add_argument("text", nargs="*", help="texto para detectar; sem texto, mostra o estado atual")
    p_emotion.set_defaults(func=_cmd_emotion)

    p_stt = sub.add_parser("stt", help="transcreve um WAV (faster-whisper, VAD calibrado)")
    p_stt.add_argument("wav", help="arquivo de áudio")
    p_stt.add_argument("--model", default="small", help="tamanho do modelo faster-whisper")
    p_stt.set_defaults(func=_cmd_stt)

    p_speak = sub.add_parser("speak", help="sintetiza texto com Kokoro (TTS)")
    p_speak.add_argument("text", help="texto a falar")
    p_speak.add_argument("--voice", default="af_heart", help="voz Kokoro")
    p_speak.add_argument("--no-play", action="store_true", help="gera WAV sem tocar")
    p_speak.set_defaults(func=_cmd_speak)

    p_voice = sub.add_parser("voice", help="loop de voz: STT → roteador → TTS (brainCommand do wakeword)")
    p_voice.add_argument("wav", help="arquivo de áudio capturado pelo wakeword")
    p_voice.add_argument("--no-tts", action="store_true", help="não sintetizar resposta em voz")
    p_voice.add_argument("--model", default="small", help="tamanho do modelo faster-whisper")
    p_voice.set_defaults(func=_cmd_voice)

    p_audiobook = sub.add_parser("audiobook", help="leitor de livros (.epub/.txt) com TTS Kokoro")
    p_audiobook.add_argument("audiobook_action",
                             choices=["scan", "list", "read", "stop", "pause", "resume", "next", "prev", "status"],
                             help="ação: scan/list/read/stop/pause/resume/next/prev/status")
    p_audiobook.add_argument("book", nargs="?", default=None, help="nome do livro (para read)")
    p_audiobook.set_defaults(func=_cmd_audiobook)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


def intent_main() -> int:  # entry point extra: jarvis-intent "texto"
    print(classify_intent(" ".join(sys.argv[1:])))
    return 0


def rag_main() -> int:  # entry point extra: jarvis-rag "busca"
    sys.argv = ["jarvis-rag", "rag", *sys.argv[1:]]
    args = build_parser().parse_args()
    return args.func(args)


def waybar_main() -> int:  # entry point extra: jarvis-waybar (module do Waybar)
    from jarvis.core.feedback import waybar_format

    print(json.dumps(waybar_format(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
