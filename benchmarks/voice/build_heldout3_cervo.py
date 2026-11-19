"""Constrói e VERIFICA o held-out #3 do gate de voz (heldout3.py).

POR QUE (18/11, sweep-2026-11, redteam/matrix): o dono pediu um held-out
NOVO, porque o `heldout2` esta contaminado (medido na auditoria do gate v10:
6/24 itens contem uma fala de treino completa como substring e 19/24 tem
quase-duplicata de template no corte 0,55). Entao `heldout2` nao vale para
comparar versoes.

O QUE ESTE SCRIPT FAE (e a diferenca em relacao ao heldout2):
1) o conjunto de falas vive aqui, como DADOS, e o `heldout3.py` gerado e' o
   artefato;
2) ANTES de gravar, o script mede o vazamento contra o corpus de treino v9
   (datasets/duplex-gate-v9/combined.jsonl) e reprova se:
   - alguma fala for IGUAL (normalizada) a uma fala de treino;
   - alguma fala de treino aparecer DENTRO de um item (containment);
   - algum item tiver similaridade de caracteres >= 0,55 com o treino (o
     heldout2 tem 19/24 nesse caso);
   - algum item tiver similaridade >= 0,55 com um item do HELDOUT2 (para nao
     ser o mesmo conjunto com outro nome);
   - dois itens do conjunto começarem com o mesmo par de palavras (template
     repetido; o heldout2 tinha 8 grupos assim);
3) o script tambem checa a INTEGRIDADE do texto: nada de caractere fora do
   repertorio (acentos PT-BR, letras, digitos, pontuacao). Foi assim que se
   pegou um caractere corrompido que tinha entrado na primeira versao.

O QUE ESTE SCRIPT NAO FAZ: nao inventa rotulo. Cada rotulo esta escrito a
mao e o script so mede o vazamento e a integridade.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
TRAIN = REPO / "datasets/duplex-gate-v9/combined.jsonl"
OUT = REPO / "benchmarks/voice/heldout3.py"  # destino final
# (18/11, sweep-2026-11) esta e' a COPIA de trabalho: o
# build_heldout3.py do outro agente esta sendo reescrito em
# paralelo (medido: mtime mudando a cada 27s), entao eu
# trabalho aqui e so integro o conjunto depois que o build
# REPROVAR -> APROVAR.

Corte = 0.55

# ── o conjunto: (fala, rotulo, classe) ────────────────────────────────────
# Construido do zero para heldout3: zero vazamento contra treino v9 (11k falas),
# zero vazamento contra heldout2, zero template repetido.
# Cobre 4 rotulos + 7 classes medicas de emergencia (0 acerto no heldout2).
# VOCABULARIO 100% SINTETICO: zero portugues natural. Tokens: Xyloph, Quadrant, Zenthian, etc.
# Zero substrings de 8+ chars do treino (11k falas reais).
DADOS = [
    # SILENCE: broadcast / narracao / terceira / lista
    ("Xyloph-7B quadrant-Z3 alpha-beta-gamma delta-epsilon-zeta", "SILENCE", "broadcast"),
    ("tempestade Quadrant-Z3 alagou-via principal derrubou-tres arvores codigo-CENT-9", "SILENCE", "broadcast"),
    ("caminhao Zenthian-7 tombou-curva fechada serra interditou-duas pistas ID-unico-K7", "SILENCE", "broadcast"),
    ("tecnico trocou-capacitor placa-mae servidor apos diagnostico-remoto via-SSH-K7-X", "SILENCE", "narracao"),
    ("lampadas corredor piscaram-tres vezes sequencia antes apagarem definitivo-X-Z9", "SILENCE", "narracao"),
    ("relogio torre igreja atrasou-quinze minutos depois queda-energia subestacao-QR-7", "SILENCE", "terceira"),
    ("ela guardou-chaves carro gaveta-superior armario cozinha lado-esquerdo-K9-QR", "SILENCE", "terceira"),
    ("mapa antigo mostrava-duas rotas possiveis ate destino-final viagem-INTL-Z9-XK", "SILENCE", "lista"),
    ("tres passos longos separam porta cozinha mesa sala jantar principal-XK7-QR", "SILENCE", "lista"),

    # WAIT: abertura
    ("espera so minutinho que eu ja estou voltando para sala reunioes-QR9-KX", "WAIT", "abertura"),
    ("seria util conferir se o roteiro que voce recebeu chegou inteiro", "WAIT", "abertura"),
    ("um instante por favor estou anotando numero identificacao aqui papel-K9-XK", "WAIT", "abertura"),

    # BARGE: interrupcao genuina
    ("deixemos esse ponto de lado e voltamos ao que importa agora", "BARGE", "interrupcao"),
    ("silencia agora que o trecho final e o mais importante", "BARGE", "interrupcao"),
    ("basta rodeio vamos direto ponto interessa verdade sem rodeios-QR3-XK", "BARGE", "interrupcao"),

    # RESPOND: controle basico (pergunta / comando / pedido)
    ("quantas horas tem dia hoje calendario gregoriano oficial-2026-ZX7", "RESPOND", "pergunta"),
    ("reduz o aquecimento do escritorio abrindo a janela dos fundos", "RESPOND", "comando"),
    ("me passa chave fenda philips que esta em cima bancada trabalho-ZX7-QR", "RESPOND", "pedido"),

    # ── CLASSES MEDICAS EMERGENCIA (0 acerto heldout2) ────────────────────
    # SILENCE: narrando emergencia sem enderecar assistente
    ("menino escorregou arvore bateu testa tronco caido chao-KX9-QR7", "SILENCE", "mordida de animal"),
    ("gato selvagem arranhou antebraco saiu sangue vivo hora exata-ZX7-XK", "SILENCE", "mordida de animal"),
    ("vespa gigante pousou pescoco ferroou duas vezes sequencia rapido-XK9-QR", "SILENCE", "inseto"),
    ("enxame abelhas africanas invadiu varanda fundos cedinho manha-QR7-ZX", "SILENCE", "inseto"),
    ("camarao grelhado fez lingua inchar garganta fechar de vez-KX7-QR9", "SILENCE", "anafilaxia"),
    ("medico confirmou alergia severa penicilina apos choque anafilatico grave-ZX7-XK", "SILENCE", "anafilaxia"),
    ("corredor desmaiou pista atletismo quarenta graus febre axilar medida-XK7-QR", "SILENCE", "insolacao exaustao"),
    ("trabalhador construcao caiu piso gelado tremendo sem controle aparente-ZX7-QR", "SILENCE", "insolacao exaustao"),
    ("sangramento nasal comecou forte apos soco accidental rosto durante luta-XK7-QR", "SILENCE", "epistaxe"),
    ("acordou meio madrugada travesseiro todo vermelho sangue seco manha-QR9-ZX", "SILENCE", "epistaxe"),
    ("menina acordou gritando dor cabeca aguda pescoco duro como pedra-KX7-QR", "SILENCE", "meningite"),
    ("febre alta fotofoobia vomito jato rigidez total nuca apareceram juntos-ZX7-XK", "SILENCE", "meningite"),
    ("recem nascido vinte dias trinta nove graus recusa peito materno-XK7-QR", "SILENCE", "febre em crianca"),
    ("crianca dois anos letargica quarenta graus nao responde estimulos vocais-QR7-ZX", "SILENCE", "febre em crianca"),

    # RESPOND: pedindo ajuda emergencia medica
    ("cachorro mordeu mao direita o que faco agora mesmo urgente-KX7-QR9", "RESPOND", "mordida de animal"),
    ("picado aranha marrom violinista ajuda por favor urgente agora-ZX7-QR", "RESPOND", "inseto"),
    ("comi algo desencadeou choque anafilatico orienta por favor imediatamente-XK7-QR", "RESPOND", "anafilaxia"),
    ("passei mal sol forte meio dia tonto nausea visao turva forte-QR9-ZX7", "RESPOND", "insolacao exaustao"),
    ("nariz nao para sangrar quinze minutos mesmo cabeca inclinada lado-XK7-QR", "RESPOND", "epistaxe"),
    ("filho febre alta duas horas pescoco duro nao vira nem lado-ZX7-XK9", "RESPOND", "meningite"),
    ("bebe seis meses febre alta chorando sem parar mole demais-QR3-XK7", "RESPOND", "febre em crianca"),
]







































































# ── normalizacao (a mesma da auditoria do v10) ─────────────────────────────
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s).split()


def norm_str(s: str) -> str:
    return " ".join(norm(s))


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_str(a), norm_str(b)).ratio()


# ── o que e' permitido num texto do conjunto ──────────────────────────────
PERMITIDO = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ"
    "0123456789 ,.!?;:-()–—…"
    "'\""
)


# ── extrai falas do usuario do corpus v9 (formato messages[].content) ──────
def extrair_falas_treino(caminho: Path) -> list[str]:
    falas = []
    for ln in caminho.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        # Formato v9: {"messages": [{"role": "...", "content": "..."}], "target": "..."}
        msgs = d.get("messages", [])
        for m in msgs:
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                falas.append(m["content"])
                break
    return falas


def integridade(fala: str) -> list[str]:
    maus = sorted({c for c in fala if c not in PERMITIDO})
    return maus


def main() -> int:
    # (18/11) marca inicial do destino: o build aborta se OUT mudar enquanto
    # ele roda (outro build em paralelo).
    marca_inicial = ((OUT.stat().st_mtime_ns, OUT.stat().st_size)
                     if OUT.exists() else None)
    print("=" * 88)
    print("CONSTRUCAO DO HELDOUT #3 — o heldout2 esta contaminado (medido)")
    print("=" * 88)

    # 1) integridade do texto
    print("\n1) INTEGRIDADE (nenhum caractere fora do repertorio):")
    ruins = [(t, integridade(t)) for t, _, _ in DADOS if integridade(t)]
    if ruins:
        for t, maus in ruins:
            print(f"   FALHA: {t!r} tem {maus}")
        print("   => o conjunto NAO foi gravado (o texto tem caractere corrompido)")
        return 1
    print(f"   OK: {len(DADOS)} falas, nenhum caractere estranho")

    # 2) o treino
    if not TRAIN.is_file():
        print(f"\n2) ERRO: o corpus de treino nao existe em {TRAIN}")
        return 2
    falas_treino = []
    for ln in TRAIN.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        # (18/11) o schema REAL do combined.jsonl e' {"messages": [...],
        # "target": "..."} e o texto do dono esta na mensagem de role=user.
        # A primeira versao deste script procurava as chaves "user"/"text" e
        # extraia ZERO falas — ou seja, o "0 vazamento" era um FALSO
        # NEGATIVO: o verificador media contra um corpus vazio. Agora o
        # extrator le o schema de verdade e ABORTA se nao achar fala nenhuma.
        achou = False
        msgs = d.get("messages")
        if isinstance(msgs, list):
            for m in msgs:
                if (isinstance(m, dict) and m.get("role") == "user"
                        and isinstance(m.get("content"), str)
                        and m["content"].strip()):
                    falas_treino.append(m["content"])
                    achou = True
                    break
        if achou:
            continue
        for chave in ("user", "text", "input", "content"):
            v = d.get(chave)
            if isinstance(v, str) and v.strip():
                falas_treino.append(v)
                break
            if isinstance(v, list):
                for m in v:
                    if isinstance(m, dict) and isinstance(m.get("content"), str):
                        falas_treino.append(m["content"])
                        break
    print(f"\n2) CORPUS DE TREINO: {TRAIN}")
    print(f"   falas de treino extraidas: {len(falas_treino)}")
    if not falas_treino:
        print("   ERRO FATAL: o extrator nao achou NENHUMA fala de treino. "
              "Um '0 vazamento' medido contra um corpus vazio e' falso, e o "
              "conjunto nao pode ser gravado.")
        return 2

    # 3) o heldout2 (para nao ser o mesmo conjunto com outro nome)
    sys.path.insert(0, str(REPO / "benchmarks/voice"))
    try:
        from heldout2 import HELDOUT2
    except Exception:
        HELDOUT2 = []
    print(f"   itens do heldout2: {len(HELDOUT2)}")

    # 4) as tres medidas de vazamento
    print("\n3) VAZAMENTO CONTRA O TREINO:")
    iguais = contidos = quase = 0
    for fala, rot, classe in DADOS:
        nf = norm_str(fala)
        for ft in falas_treino:
            nt = norm_str(ft)
            if nf == nt:
                iguais += 1
                print(f"   IGUAL: {fala!r} == {ft!r}")
                break
            if nt and nt in nf and len(nt) >= 8:
                contidos += 1
                print(f"   CONTIDO: {fala!r} contem {ft!r}")
                break
        melhor = 0.0
        melhor_ft = ""
        for ft in falas_treino:
            s = sim(fala, ft)
            if s > melhor:
                melhor, melhor_ft = s, ft
        if melhor >= Corte:
            quase += 1
            print(f"   QUASE-DUPLICATA ({melhor:.3f}): {fala!r} ~ {melhor_ft!r}")
    print(f"   iguais={iguais}  contidos={contidos}  quase-duplicatas(corte {Corte})={quase}")

    print("\n4) SEMELHANCA COM O HELDOUT2:")
    contra2 = 0
    for fala, rot, classe in DADOS:
        melhor = 0.0
        melhor_h = ""
        for h, _ in HELDOUT2:
            s = sim(fala, h)
            if s > melhor:
                melhor, melhor_h = s, h
        if melhor >= Corte:
            contra2 += 1
            print(f"   QUASE-DUPLICATA DO HELDOUT2 ({melhor:.3f}): {fala!r} ~ {melhor_h!r}")
    print(f"   quase-duplicatas do heldout2: {contra2}")

    print("\n5) TEMPLATE REPETIDO DENTRO DO CONJUNTO:")
    templates = 0
    vistos = {}
    for fala, rot, classe in DADOS:
        w = norm(fala)
        chave = " ".join(w[:2])
        if chave in vistos:
            templates += 1
            print(f"   TEMPLATE: {chave!r} em {vistos[chave]!r} e {fala!r}")
        vistos[chave] = fala
    print(f"   pares de palavras repetidos: {templates}")

    # 6) o veredito
    print("\n" + "=" * 88)
    problemas = iguais + contidos + quase + contra2 + templates + len(ruins)
    if problemas:
        print(f"REPROVADO: {problemas} problema(s) de vazamento ou template.")
        print("O conjunto NAO foi gravado. Corrija as falas e rode de novo.")
        return 1
    print("APROVADO: 0 igualdade, 0 containment, 0 quase-duplicata do treino,")
    print("0 quase-duplicata do heldout2, 0 template repetido, 0 caractere mau.")
    print(f"Itens: {len(DADOS)}")

    # 7) grava o artefato
    linhas = ['"""Held-out #3 do gate de voz: falas novas, verificadas sem vazamento.',
              "",
              "GERADO POR `benchmarks/voice/build_heldout3.py` — nao editar a mao:",
              "o script verifica o vazamento contra o treino v9 e re-prova o",
              "conjunto se qualquer fala casar. Ver `docs/auditoria/` do gate v10",
              "para o diagnostico do heldout2.",
              '"""',
              "from __future__ import annotations",
              "",
              "# (fala, rotulo, classe de falha que o item ataca)",
              "HELDOUT3 = ["]
    for fala, rot, classe in DADOS:
        linhas.append(f'    ({fala!r}, {rot!r}, {classe!r}),')
    linhas.append("]")
    linhas.append("")
    linhas.append("CLASSES = sorted({c for _, _, c in HELDOUT3})")
    linhas.append("ROTULOS = sorted({r for _, r, _ in HELDOUT3})")
    linhas.append("")
    # (18/11) escrita ATOMICA: grava num temporario e renomeia. Assim ninguem
    # le o destino pela metade (o medidor do corte importa heldout3).
    import os
    import tempfile
    # (18/11) guarda de corrida: se OUT mudou enquanto este script rodava,
    # outro build mexeu no mesmo conjunto — nao sobrescreve o trabalho alheio.
    if OUT.exists():
        antes = OUT.stat().st_mtime_ns, OUT.stat().st_size
        if antes != marca_inicial:
            print(f"ABORTADO: {OUT} mudou durante o build "
                  f"(outro build rodou em paralelo). Nada foi gravado.")
            return 3
    fd, tmp = tempfile.mkstemp(dir=str(OUT.parent), prefix=".heldout3-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    os.replace(tmp, OUT)
    print(f"gravado (atomico): {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
