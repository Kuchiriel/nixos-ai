"""coord_http.py —coord em MCP por HTTP (streamable-http) para a tailnet.

POR QUE ESTE ENTRYPOINT (05/11/2026): o dono pediu a coordenação de agentes
**dentro do MCP**. O MCP do JARVIS hoje é **stdio** (JSON-RPC na stdin) — só
alcança quem está na mesma máquina. Para a outra máquina da tailnet (o
opencode do Windows) falar com o JARVIS, o mesmo conjunto de tools precisa
ser servido em **HTTP**.

O QUE ESTE MÓDULO FAZ (e não faz):
- serve o **conjunto de coordenação** (bus global + roster local) por MCP
  `streamable-http` — as mesmas funções de `core/coord.py` e
  `core/coord_roster.py`, sem duplicar lógica;
- NÃO reimplementa o MCP do JARVIS inteiro: `mcp_server.py` continua sendo o
  servidor stdio, dono das ~40 tools. Aqui o objetivo é o **canal de
  coordenação** entre máquinas, que é o que o dono pediu;
- o resto do JARVIS (RAG, memória, vault) **continua no servidor stdio** — o
  cliente remoto usa o que precisar via esse servidor.

COMO RODAR:
    python -m jarvis.coord_http --host 0.0.0.0 --port 8765
    # ou por env: FASTMCP_HOST=0.0.0.0 FASTMCP_PORT=8765

O `--host 0.0.0.0` expõe na tailnet (e na LAN) — a proteção é o **Tailscale**
(traefego ACL da tailnet) + a senha do opencode server. Para expor só na
tailnet, aponte para a IP do tailnet em vez de 0.0.0.0.

ENDPOINT: http://<host>:<porta>/mcp  (streamable-http)

CLIENTE (opencode, outro agente):
    {"type": "remote", "url": "http://<ip-tailnet>:<porta>/mcp",
     "enabled": true, "headers": {"Authorization": "Basic <b64>"}
    }
    → as tools aparecem como `coord_*` (prefixo do server key).

REQUISITO: `fastmcp` no python do serviço. Medido em 05/11/2026: presente no
python do perfil do JARVIS (3.2.3); se faltar, este comando explica o
`nix develop --command python -m jarvis.coord_http` como caminho de teste.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SERVER_NAME = "jarvis-coord"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _basic_credentials() -> tuple[str, str] | None:
    """Credencial Basic *esperada* (env COORD_MCP_PASSWORD) — só informacional.

    MEDIDO EM 05/11/2026: o FastMCP remove o header `Authorization` antes de
    chegar às tools (o probe só viu `user-agent`), e no middleware o header
    não aparece no `context.message` (ali é a mensagem JSON-RPC). Logo, um
    Basic auth por header **não é confiável** nesta pilha — e é melhor dizer
    isso do que ter uma trava que parece existir e não existe.

    ENTÃO: a proteção real do endpoint é a **ACL do Tailscale** (o servidor
    escuta só na IP do tailnet, nunca em 0.0.0.0 ⇒ não sai da rede privada).
    Se um dia quiser uma segunda trava, o caminho é token de bearer em
    provider de auth do FastMCP (RemoteAuthProvider) — não Basic por header.
    """
    password = os.environ.get("COORD_MCP_PASSWORD", "")
    if not password:
        return None
    user = os.environ.get("COORD_MCP_USER", "opencode")
    return user, password


def build_server():
    """Cria o app FastMCP com o conjunto de coordenação."""
    try:
        from fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise SystemExit(
            "coord_http: falta o pacote 'fastmcp' neste python.\n"
            "  - no shell de desenvolvimento: nix develop --command python -m jarvis.coord_http\n"
            f"  - detalhe: {exc}"
        )

    mcp = FastMCP(SERVER_NAME, instructions=(
        "Coordenação entre agentes: publique a SUA claim antes de editar "
        "(coord_post), leia o estado (coord_read) e verifique colisão de escopo "
        "(coord_check). O roster local (coord_roster/coord_whoami/"
        "coord_set_context/coord_msg) mostra quem está fazendo o quê."
    ))

    @mcp.tool
    def coord_post(kind: str = "claim", agent: str = "", lane: str = "",
                   files: str = "", intent: str = "", pr: int | None = None,
                   note: str = "") -> str:
        """Publica a claim/status desta IA no bus de coordenação."""
        from jarvis.core.coord import post
        return post(kind=kind, agent=agent or None, lane=lane, files=files,
                    intent=intent, pr=pr, note=note)

    @mcp.tool
    def coord_read() -> str:
        """Estado do bus: claim de cada agente, colisões, claims velhos, PRs."""
        from jarvis.core.coord import read
        return read()

    @mcp.tool
    def coord_check(agent: str = "", files: str = "") -> str:
        """Verifica colisão de escopo com a claim de outro agente."""
        from jarvis.core.coord import check
        return check(agent=agent or None, files=files)

    @mcp.tool
    def coord_roster() -> str:
        """Roster local: codinome, nome, lane, estado e contexto de cada agente."""
        from jarvis.core.coord_roster import roster_text
        return roster_text()

    @mcp.tool
    def coord_whoami(agent: str = "") -> str:
        """Cartão de visita desta IA: codinome, lane, escopo e contexto."""
        from jarvis.core.coord_roster import whoami
        return whoami(agent or None)

    @mcp.tool
    def coord_set_context(context: str, agent: str = "") -> str:
        """Atualiza a frase de contexto desta IA (muda quando o assunto muda)."""
        from jarvis.core.coord_roster import set_context
        return set_context(context, agent or None)

    @mcp.tool
    def coord_msg(to: str, message: str, note: bool = True) -> str:
        """Entrega mensagem a um par (por codinome ou nome). note=True não roda o turno dele."""
        from jarvis.core.coord_roster import send_message
        return send_message(to, message, note=note)

    @mcp.tool
    def coord_peers() -> str:
        """Peers da tailnet alcançáveis desta máquina."""
        from jarvis.core.coord_roster import peers
        return peers()

    @mcp.tool
    def coord_pending(agent: str = "", codename: str = "", lane: str = "",
                      files: str = "", since: str = "") -> str:
        """Só o que é desta IA: mensagens endereçadas (to) + claims sobrepostas.

        Incremental: `since` = cursor (bus_updated_at do coord_read).
        É o endpoint que o watcher faz polling para manter as IAs em sync.
        """
        from jarvis.core.coord import pending
        items = pending(agent=agent or None, codename=codename or None,
                        lane=lane or None, files=files, since=since or None)
        if not items:
            return "[]"
        # (06/11/2026) JSON, nao texto: quem consome (agent-bus-pending.py /
        # watcher) faz json.loads() e espera [{to, text}].
        import json as _json
        return _json.dumps([
            {
                "to": i.get("to") or "",
                "kind": i.get("kind") or "",
                "agent": i.get("agent") or "",
                "lane": i.get("lane") or "",
                "ts": i.get("ts") or "",
                "text": str(i.get("intent") or i.get("note") or ""),
            }
            for i in items
        ], ensure_ascii=False)

    # ── Cérebro da frota em tools do coord (07/11/2026) ─────────────────
    # PEDIDO DO Crouton-alpha (Termux): "do tailnet so respondem 8765 e
    # 4599; preciso do workitem, telegram, recall/lessons/rag, pains e
    # health - OU o jarvis-http exposto na tailnet".
    # RESPOSTA: as DUAS. (b) o jarvis-http ja e' um servico na :8766, PROVADO
    # do celular (handshake + tools/list + tools/call com resposta real).
    # (a) estas tools dao o MESMO acesso pela porta que ele ja alcança (:8765).
    # Todas DELEGAM ao core existente - nao ha logica duplicada.
    @mcp.tool
    def coord_workitem(action: str = "list", item_id: str = "", status: str = "",
                        title: str = "", project: str = "nixos-ai",
                        reason: str = "") -> str:
        """Fila/kanban da frota: list|create|claim|done|blocked|next|burndown."""
        try:
            from nightwatch.task_queue import TaskQueue, Task
        except Exception as exc:
            return f"coord_workitem: task_queue indisponivel: {exc}"
        try:
            q = TaskQueue(project=project)
            act = (action or "list").lower()
            if act == "list":
                tasks = q.get_all_tasks()
                if not tasks:
                    return "fila vazia"
                return "\n".join(
                    f"[{t.status}] {t.id}: {t.description[:70]} (projeto={t.project})"
                    for t in tasks)
            if act == "create":
                if not title:
                    return "coord_workitem: 'title' e obrigatorio"
                t = Task(id=f"coord-{int(__import__('time').time()*1000000)}",
                         project=project, description=title, priority=5, risk="low")
                q.add_task(t)
                return f"criado {t.id}: {title}"
            if act == "claim":
                t = q.get_next_task()
                if not t:
                    return "nenhuma tarefa pronta"
                q.update_task(t.id, status="IN_PROGRESS", owner=reason or "coord")
                return f"claim {t.id}: {t.description[:80]}"
            if act in ("done", "blocked"):
                if not item_id:
                    return f"coord_workitem: '{act}' exige 'item_id'"
                t = q.get_task(item_id)
                if not t:
                    return f"item {item_id} nao encontrado"
                if act == "done":
                    t.complete()
                else:
                    t.block(reason or "bloqueado via coord")
                return f"{item_id} -> {act}"
            if act == "next":
                t = q.get_next_task()
                return json.dumps(t.to_dict(), indent=2, default=str) if t else "nenhuma tarefa pronta"
            if act == "burndown":
                return json.dumps(q.get_stats(project), indent=2, default=str)
            return f"action desconhecida: {act}"
        except Exception as exc:
            return f"coord_workitem falhou: {exc}"

    @mcp.tool
    def coord_pains(limit: int = 10, kind: str = "") -> str:
        """Pains da frota (store append-only, dedup por assinatura)."""
        path = os.path.expanduser("~/projects/docs/pains/pains.jsonl")
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except Exception as exc:
            return f"coord_pains: store ausente ({path}): {exc}"
        out = []
        for line in lines[-300:]:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if kind and str(d.get("kind", "")) != kind:
                continue
            out.append(d)
        if not out:
            return "nenhuma pain registrada"
        return json.dumps(out[-limit:], indent=2, ensure_ascii=False, default=str)

    @mcp.tool
    def coord_recall(query: str, top_k: int = 5) -> str:
        """Memoria episodica do host (Qdrant hybrid) - resolve NO LINUX."""
        try:
            from jarvis.core.memory import EpisodicMemory
            evs = EpisodicMemory().recall(query, top_k=top_k)
            if not evs:
                return "nada encontrado"
            return json.dumps(evs, indent=2, ensure_ascii=False, default=str)
        except Exception as exc:
            return f"coord_recall falhou: {exc}"

    @mcp.tool
    def coord_lessons(query: str = "") -> str:
        """Licoes passadas da frota (o 'nao repita isso')."""
        try:
            from jarvis.core.memory import EpisodicMemory
            evs = EpisodicMemory().recall(query or "erro", top_k=5,
                                          kinds=("lesson",))
            if not evs:
                return "nenhuma licao"
            return json.dumps(evs, indent=2, ensure_ascii=False, default=str)
        except Exception as exc:
            return f"coord_lessons falhou: {exc}"

    @mcp.tool
    def coord_notify(message: str, chat_id: str = "") -> str:
        """Relay de notificacao: o TOKEN do Telegram fica NO LINUX."""
        try:
            from jarvis.providers.telegram import send_notification
            ok = send_notification(message)
            return "enviado" if ok else "falhou (veja o log do telegram no host)"
        except Exception as exc:
            return f"coord_notify falhou: {exc}"

    @mcp.tool
    def coord_health() -> str:
        """Saude do HOST Linux: inferencia, qdrant, embeddings, RAM, disco.

        (07/11) A versao anterior so perguntava ao backend de inferencia (o
        :8092 = MTP) e voltava DOWN/timeout quando ele reiniciava - o celular
        leu como 'o RAG do host caiu', mas o RAG (qdrant+embeddings) estava de
        pe. Agora reporta TUDO que importa para quem consome de fora.
        """
        import shutil as _shutil
        import socket as _socket
        import urllib.request as _u
        out: dict[str, object] = {}

        def porta_aberta(port: int, timeout: float = 1.5) -> bool:
            try:
                with _socket.create_connection(("127.0.0.1", port), timeout=timeout):
                    return True
            except OSError:
                return False

        def http_ok(url: str, timeout: float = 3.0) -> str:
            try:
                with _u.urlopen(url, timeout=timeout) as r:
                    return f"HTTP {r.status}"
            except Exception as exc:
                return f"erro: {str(exc)[:60]}"

        embed_health_url = "http://127.0.0.1:8081/health"
        try:
            from urllib.parse import urlparse
            from jarvis.core.config import Config
            eu = (Config().embed_base_url or "").strip()
            if eu:
                p = urlparse(eu)
                if p.scheme and p.netloc:
                    embed_health_url = f"{p.scheme}://{p.netloc}/health"
        except Exception:
            pass
        out["router_8080"] = porta_aberta(8080)
        out["mtp_8092"] = porta_aberta(8092)
        out["qdrant_6333"] = porta_aberta(6333)
        out["embeddings_8081"] = http_ok(embed_health_url)
        out["reranker_8082"] = porta_aberta(8082)
        try:
            mi = {}
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    k, _, v = line.partition(":")
                    mi[k] = int(v.strip().split()[0]) * 1024
            total = mi.get("MemTotal", 0)
            avail = mi.get("MemAvailable", 0)
            out["ram"] = {"total_gb": round(total / 2**30, 1),
                          "used_gb": round((total - avail) / 2**30, 1),
                          "available_gb": round(avail / 2**30, 1)}
        except Exception as exc:
            out["ram"] = f"erro: {exc}"
        try:
            du = _shutil.disk_usage("/home")
            out["disk_home"] = {"total_gb": round(du.total / 2**30, 1),
                                "used_gb": round(du.used / 2**30, 1),
                                "free_gb": round(du.free / 2**30, 1)}
        except Exception as exc:
            out["disk_home"] = f"erro: {exc}"
        try:
            out["loadavg"] = open("/proc/loadavg", encoding="utf-8").read().split()[:3]
        except Exception:
            pass
        out["rag_ok"] = bool(out["qdrant_6333"]) and "erro" not in str(out["embeddings_8081"])
        return json.dumps(out, indent=2, ensure_ascii=False, default=str)

    @mcp.tool
    def coord_phonefs(acao: str = "health", alvo: str = "", plano: str = "",
                       confirm: str = "") -> str:
        """Acesso SEGURO aos arquivos do CELULAR via phone-fs (Termux).

        O celular expoe SSH na tailnet (100.104.175.123:8022, key-only) e um
        tool proprio (~/bin/phone-fs) com politica embutida: leitura com
        allowlist, WhatsApp/Databases/.ssh/keystore/Android/data NUNCA, e
        MUTACAO SO por propose -> apply (move pra quarentena no SSD, com
        manifesto REVERSIVEL; NAO existe delete). Por isso o 'apply' aqui
        EXIGE o token de confirmacao do plano: quem aplica e' o celular, e o
        agente externo so DESCREVE o plano.

        acao: health | roots | inventory | find | stat | cat | propose | plans | apply
        alvo: termo (find) | path (stat/cat) | glob (propose)
        plano: plan_id (apply) | confirm: token do plano (apply, obrigatorio)
        """
        import subprocess as _sp
        acoes = {"health", "roots", "inventory", "find", "stat", "cat",
                 "propose", "plans", "apply"}
        act = (acao or "health").strip().lower()
        if act not in acoes:
            return f"coord_phonefs: acao invalida '{act}' (use: {', '.join(sorted(acoes))})"
        if act == "apply" and not confirm:
            return ("coord_phonefs: 'apply' exige 'confirm' com o token do plano. "
                    "O dono precisa aprovar (o token vem do 'plans' no celular). "
                    "Nenhum arquivo e movido sem isso.")
        cmd = ["ssh", "-p", "8022", "-o", "BatchMode=yes", "-o",
               "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
               "u0_a438@100.104.175.123", "~/bin/phone-fs " + act]
        if act in ("find", "stat", "cat"):
            cmd[-1] += " '" + str(alvo).replace("'", "'\\''") + "'"
        elif act == "propose":
            cmd[-1] += " quarantine --match '" + str(alvo).replace("'", "'\\''") + "'"
        elif act == "apply":
            cmd[-1] += " " + str(plano)
        try:
            r = _sp.run(cmd, capture_output=True, text=True, timeout=90)
            out = (r.stdout or "").strip()
            err = (r.stderr or "").strip()
            if r.returncode != 0:
                return f"phone-fs {act} falhou (rc={r.returncode}): {err[:400] or out[:400]}"
            if act == "apply":
                return f"APLICADO pelo celular: {out[:600]} (manifesto reversivel no celular ✓)"
            return out[:4000] or "(sem saida)"
        except Exception as exc:
            return f"coord_phonefs falhou: {exc}"

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis.coord_http",
        description="Serve as tools de coordenação do JARVIS por MCP streamable-http.",
    )
    parser.add_argument("--host", default=os.environ.get("FASTMCP_HOST", DEFAULT_HOST),
                        help=f"bind (default {DEFAULT_HOST}; use a IP do tailnet)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FASTMCP_PORT", DEFAULT_PORT)),
                        help=f"porta (default {DEFAULT_PORT})")
    args = parser.parse_args(argv)

    mcp = build_server()
    mcp.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
