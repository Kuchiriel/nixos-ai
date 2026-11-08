"""Testes do time (equipe): persona por tarefa, modelo e o plano.

O QUE ESTES TESTES PROVAM:
  - a tarefa classifica no tipo certo e a persona (MBTI) acompanha o tipo
    (o paper mede: alinhar personalidade×tarefa melhora o pass rate);
  - a escolha de modelo NUNCA devolve um modelo em cooldown de rate limit
    (o guard do provider avisa; trocar é obrigatório, não opcional);
  - o plano é montável sem rede e sem tocar no bus (o time decide, quem
    executa é o opencode).
"""
from __future__ import annotations

from jarvis.core import team


def test_classificacao_por_palavra_chave():
    assert team.classify("corrigir o bug do timeout")[0] == "debug"
    assert team.classify("arquitetar o protocolo do bus")[0] == "arquitetura"
    assert team.classify("pesquisar papers de refusal no arxiv")[0] == "pesquisa"
    assert team.classify("escrever a documentação no agents.md")[0] == "documentacao"
    assert team.classify("deploy do serviço e monitor de liveness")[0] == "operacao"


def test_persona_acompanha_a_tarefa():
    mbti, pid, why = team.persona_for_task("corrigir o bug do traceback")
    assert mbti == "ISTP"
    assert pid
    assert why
    mbti2, _, _ = team.persona_for_task("arquitetar o sistema de mensagens")
    assert mbti2 != mbti, "tarefas diferentes devem ter personalities diferentes"


def test_modelo_nunca_e_um_modelo_em_cooldown(monkeypatch):
    models = [
        {"id": "local/forte", "local": True, "tier": "reasoning", "capability": 9},
        {"id": "nvidia/barato", "local": False, "tier": "api", "capability": 1},
    ]
    monkeypatch.setattr(team, "_in_cooldown", lambda mid, minutes=10: mid == "local/forte")
    picked, why = team.model_for_task("corrigir o bug", models)
    assert picked != "local/forte", "modelo em cooldown foi escolhido"
    assert picked and why


def test_plano_monta_sem_rede():
    agents = [
        {"name": "A", "codename": "Arara", "files": ["x/**", "y/**"], "busy": False, "session": "s1"},
        {"name": "B", "codename": "Cervo", "files": [], "busy": False, "session": "s2"},
    ]
    plan = team.assign("corrigir o bug do watcher", agents=agents)
    assert plan["kind"] == "debug"
    assert plan["persona"]["mbti"]
    # escolhe o com MENOS escopo declarado (mais livre)
    assert plan["agent"]["name"] == "Cervo"
    assert plan["agent"]["free"] is True
    assert "MBTI" in plan["note"] or "persona" in plan["note"].lower()


def test_plano_sem_agentes_livres_marca_ocupado():
    agents = [{"name": "A", "codename": "Arara", "files": [], "busy": True, "session": "s1"}]
    plan = team.assign("qualquer tarefa", agents=agents)
    assert plan["agent"]["free"] is False
