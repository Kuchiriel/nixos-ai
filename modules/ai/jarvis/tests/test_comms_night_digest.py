"""Testa a separacao do digest da noite: o que exige acao e o que e informativo.

Medido 10/11 (sweep-2026-11): o digest contava tudo que estava enderecado
ao agente (391 itens para sweep-2026-11, 143 para a coord-naming) e listava
os 5 ultimos, que podiam ser todos status de outra lane. As lanes abriram
a lista para descobrir que nada era delas. A contagem que importa e a de
itens que exigem acao.
"""
from jarvis.core.comms import classify_pending, digest_lines


def _p(kind, agent, note="", why="endereçado", to="Cervo", lane="x/y"):
    return {"kind": kind, "agent": agent, "note": note, "to": to,
            "lane": lane, "_why": why}


def test_mensagem_enderecada_exige_acao():
    acao, info = classify_pending([_p("msg", "outra", "me avisa de algo")])
    assert len(acao) == 1
    assert not info


def test_status_de_outra_lane_e_informativo():
    acao, info = classify_pending([_p("status", "agente-remoto", "scan rodando",
                                      why="endereçado")])
    # status enderecado que so informa estado nao exige acao
    assert not acao
    assert len(info) == 1


def test_status_que_nomeia_bloqueio_continua_informativo():
    # (10/11) status e RELATORIO DE ESTADO por convencao da casa, mesmo
    # quando endereçado a voce e mesmo quando cita um bloqueio: o evento de
    # bloqueio explicito e o kind "blocked". Uma heuristica por palavra
    # classificava 347 dos 393 itens do sweep como acao, porque os status
    # longos da lane do celular citam "esperando" e "preciso" em algum
    # ponto. Regra por kind: 0 falsos positivos.
    acao, info = classify_pending(
        [_p("status", "outra", "a lane esta travada esperando o rebuild")])
    assert not acao
    assert len(info) == 1


def test_handoff_e_blocked_enderecados_exigem_acao():
    acao, _ = classify_pending([
        _p("handoff", "outra", "passo a tarefa"),
        _p("blocked", "outra", "travei aqui"),
    ])
    assert len(acao) == 2


def test_status_de_escopo_sobreposto_e_informativo():
    acao, info = classify_pending(
        [_p("status", "outra", "status qualquer", why="escopo sobreposto")])
    assert not acao
    assert len(info) == 1


def test_a_linha_do_digest_diz_o_que_exige_acao():
    pend = [_p("status", "agente-remoto", "scan de rede rodando")] * 7
    pend.append(_p("msg", "coord-naming", "preciso de uma decisao"))
    linhas = digest_lines("sweep-2026-11", pend)
    # a janela do digest e o que ele mostra; o historico vem a parte
    assert linhas[0].startswith("[noite] 5 item(ns) no digest para sweep-2026-11:")
    # a janela e os ultimos 5: 4 status + a msg do fim
    assert "1 exige(m) acao" in linhas[0]
    assert "4 informativo(s)" in linhas[0]
    assert "8 no historico do bus" in linhas[0]


def test_digest_sem_acao_e_uma_linha_curta():
    pend = [_p("status", "agente-remoto", "status de outra lane")]
    linhas = digest_lines("coord-naming", pend)
    assert linhas[0].startswith("[noite] 1 item(ns) no digest para coord-naming:")
    assert "0 exige(m) acao" in linhas[0]
    assert len(linhas) <= 3


def test_a_janela_mostra_os_acionaveis_e_nao_o_historico():
    # (10/11) o que importa e a janela: um pedido novo no meio de 300
    # itens antigos de outra lane tem que aparecer.
    pend = [_p("status", "agente-remoto", "status antigo")] * 300
    pend.append(_p("msg", "coord-naming", "TRABALHO PARA VOCE: revisar o bus"))
    linhas = digest_lines("sweep-2026-11", pend)
    assert "1 exige(m) acao" in linhas[0]
    assert any("TRABALHO PARA VOCE" in l for l in linhas)


def test_ordenacao_preservada():
    pend = [_p("msg", "a", "primeira"), _p("msg", "b", "segunda")]
    acao, _ = classify_pending(pend)
    assert [p["note"] for p in acao] == ["primeira", "segunda"]


def test_o_digest_da_noite_e_informativo_e_nao_acao():
    # (10/11) o proprio digest entra no bus como msg (o transporte nao tem
    # kind proprio), mas e RELATORIO: medido, 324 dos 393 itens pendentes do
    # sweep eram digests antigos, e a contagem crescia sozinha.
    acao, info = classify_pending(
        [_p("msg", "jarvis@nitro-v15", "[noite] 364 item(ns) pendentes no bus")])
    assert not acao
    assert len(info) == 1


def test_msg_normal_continua_exigindo_acao():
    acao, info = classify_pending(
        [_p("msg", "outra", "preciso de uma decisao do dono")])
    assert len(acao) == 1
    assert not info
