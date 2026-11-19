#!/usr/bin/env python3
"""
Teste A/B da lógica do plugin consulta-obrigatoria.

Simula o comportamento do plugin (funções de decisão extraídas) com e sem
consulta prévia, e mede o impacto:
- Grupo A (sem guarda): ação sempre liberada (status quo)
- Grupo B (com guarda): ação barrada se não houver consulta prévia

Métricas:
  - taxa_de_bloqueio: % de ações de decisão barradas no grupo B
  - acoes_sem_consulta: quantas ações de decisão ocorreram sem consulta
  - falsos_positivos: comandos read-only barrados (deveria ser 0)
  - falsos_negativos: comandos de escrita liberados sem consulta (deveria ser 0)
"""

import json
import re
import sys

# ============================================================
# Lógica extraída do plugin consulta-obrigatoria.js
# ============================================================

READ_ONLY_RE = re.compile(
    r'^\s*(echo|printf|cat|head|tail|less|more|grep|rg|awk|sed|cut|sort|uniq|wc|find|ls|pwd|whoami|date|hostname|uptime|free|df|du|ps|ss|netstat|git\s+(status|diff|log|show|ls-files|branch|remote|config\s+--get|list|stash\s+list|rev-parse|diff--stat)\b|nix\s+(flake\s+check|search|eval|build\b.*--no-link|ls|registry|why-depends)\b)',
    re.IGNORECASE,
)

STATE_CHANGE_RE = re.compile(
    r'^\s*(rm\s|mv\s|cp\s|>\s|>>\s|dd\s|nixos-rebuild|docker\s+system\s+prune|pip\s+install|npm\s+install\s+-g|curl\s.*-X\s+(POST|PUT|DELETE)|systemctl\s+(start|stop|restart|enable|disable)|reboot|shutdown)',
    re.IGNORECASE,
)

CONSULT_MCP_RE = re.compile(r'^(jarvis_)?(rehydrate|rag_search|recall|lessons)$')
ACTION_MCP_RE = re.compile(r'^(jarvis_)?(coord_post|agent_spawn|agent_wake|str_replace|write_file)$')

CONSULTED = set()

def mark_consulted(tool_name, sid=None):
    if CONSULT_MCP_RE.match(tool_name or ""):
        CONSULTED.add(sid or "global")

def is_consulted(sid=None):
    return (sid or "global") in CONSULTED

def should_block(tool, command=None, sid=None):
    """Retorna (bloqueado: bool, motivo: str ou None)."""
    tool_lower = (tool or "").lower()

    # MCP de ação?
    if ACTION_MCP_RE.match(tool_lower):
        if not is_consulted(sid):
            return True, "MCP de ação sem consulta prévia"
        return False, None

    # Comando bash/shell de mudança de estado?
    if tool_lower in ("bash", "shell") and command:
        if READ_ONLY_RE.match(command):
            return False, None
        if STATE_CHANGE_RE.match(command):
            if not is_consulted(sid):
                return True, "Comando de estado sem consulta prévia"
            return False, None

    return False, None

# ============================================================
# Cenários de teste
# ============================================================

TESTS = [
    # (nome, grupo, tool, command, sid, ja_consultou, esperado_bloqueio, esperado_motivo_contem)
    ("read-only grep sem consulta", "B", "bash", "grep -r foo src/", "s1", False, False, None),
    ("read-only ls sem consulta", "B", "bash", "ls -la", "s1", False, False, None),
    ("bash rm sem consulta", "B", "bash", "rm -rf /tmp/foo", "s1", False, True, "sem consulta prévia"),
    ("bash rm APÓS consulta", "B", "bash", "rm -rf /tmp/foo", "s1", True, False, None),
    ("str_replace sem consulta", "B", "jarvis_str_replace", None, "s1", False, True, "sem consulta prévia"),
    ("str_replace APÓS consulta", "B", "jarvis_str_replace", None, "s1", True, False, None),
    ("coord_post sem consulta", "B", "jarvis_coord_post", None, "s1", False, True, "sem consulta prévia"),
    ("coord_post APÓS consulta", "B", "jarvis_coord_post", None, "s1", True, False, None),
    ("agent_wake sem consulta", "B", "jarvis_agent_wake", None, "s1", False, True, "sem consulta prévia"),
    ("jarvis_rag_search (consulta)", "B", "jarvis_rag_search", None, "s1", False, False, None),
    ("jarvis_recall (consulta)", "B", "jarvis_recall", None, "s1", False, False, None),
    ("jarvis_rehydrate (consulta)", "B", "jarvis_rehydrate", None, "s1", False, False, None),
    ("jarvis_lessons (consulta)", "B", "jarvis_lessons", None, "s1", False, False, None),
    # Grupo A (sem guarda): nunca bloqueia
    ("grupo A: bash rm sem consulta", "A", "bash", "rm -rf /tmp/foo", "s1", False, False, None),
    ("grupo A: str_replace sem consulta", "A", "jarvis_str_replace", None, "s1", False, False, None),
]

def run():
    results = []
    falsos_positivos = 0
    falsos_negativos = 0
    acoes_sem_consulta_b = 0
    acoes_decisao_b = 0

    for nome, grupo, tool, command, sid, ja_consultou, esperado_bloqueio, esperado_motivo in TESTS:
        # Cada teste começa com CONSULTED limpo (estado de sessão nova)
        CONSULTED.clear()
        # Se o cenário diz que já consultou, marca antes de avaliar
        if ja_consultou:
            mark_consulted("jarvis_rag_search", sid)

        # Grupo A (sem guarda): nunca bloqueia
        if grupo == "A":
            bloqueado, motivo = False, None
        else:
            bloqueado, motivo = should_block(tool, command, sid)

        ok = (bloqueado == esperado_bloqueio)
        motivo_ok = True
        if esperado_motivo and bloqueado:
            motivo_ok = esperado_motivo in (motivo or "")

        status = "PASS" if (ok and motivo_ok) else "FAIL"
        results.append({
            "nome": nome,
            "grupo": grupo,
            "bloqueado": bloqueado,
            "esperado_bloqueio": esperado_bloqueio,
            "motivo": motivo,
            "status": status,
        })

        # Métricas apenas para grupo B
        if grupo == "B":
            is_acao_decisao = ACTION_MCP_RE.match(tool_lower := (tool or "").lower()) or \
                              (tool_lower in ("bash", "shell") and command and STATE_CHANGE_RE.match(command))
            if is_acao_decisao:
                acoes_decisao_b += 1
                if not ja_consultou:
                    acoes_sem_consulta_b += 1

            # Falso positivo: read-only barrado
            if bloqueado and READ_ONLY_RE.match(command or ""):
                falsos_positivos += 1
            # Falso negativo: escrita liberada sem consulta
            if not bloqueado and not ja_consultou and STATE_CHANGE_RE.match(command or ""):
                falsos_negativos += 1

    # Relatório
    total = len(results)
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = total - pass_count

    print("=== Teste A/B: consulta-obrigatoria ===")
    print(f"Total de testes: {total}")
    print(f"Passou: {pass_count} | Falhou: {fail_count}")
    print()
    print("Detalhes:")
    for r in results:
        print(f"  [{r['status']}] {r['nome']} (grupo {r['grupo']}) -> bloqueado={r['bloqueado']}, esperado={r['esperado_bloqueio']}")
    print()
    print("=== Métricas grupo B ===")
    print(f"  Ações de decisão: {acoes_decisao_b}")
    print(f"  Ações de decisão sem consulta: {acoes_sem_consulta_b}")
    print(f"  Falsos positivos (read-only barrado): {falsos_positivos}")
    print(f"  Falsos negativos (escrita sem consulta): {falsos_negativos}")
    print()

    if fail_count > 0 or falsos_positivos > 0 or falsos_negativos > 0:
        print("RESULTADO: FALHOU")
        return 1
    print("RESULTADO: PASSOU")
    return 0

if __name__ == "__main__":
    sys.exit(run())
