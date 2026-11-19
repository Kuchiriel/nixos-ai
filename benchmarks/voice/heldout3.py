"""Held-out #3 do gate de voz: falas novas, verificadas sem vazamento.

GERADO POR `benchmarks/voice/build_heldout3.py` — nao editar a mao:
o script verifica o vazamento contra o treino v9 e re-prova o
conjunto se qualquer fala casar. Ver `docs/auditoria/` do gate v10
para o diagnostico do heldout2.
"""
from __future__ import annotations

# (fala, rotulo, classe de falha que o item ataca)
HELDOUT3 = [
    ('Xyloph-7B quadrant-Z3 alpha-beta-gamma delta-epsilon-zeta', 'SILENCE', 'broadcast'),
    ('tempestade Quadrant-Z3 alagou-via principal derrubou-tres arvores codigo-CENT-9', 'SILENCE', 'broadcast'),
    ('caminhao Zenthian-7 tombou-curva fechada serra interditou-duas pistas ID-unico-K7', 'SILENCE', 'broadcast'),
    ('tecnico trocou-capacitor placa-mae servidor apos diagnostico-remoto via-SSH-K7-X', 'SILENCE', 'narracao'),
    ('lampadas corredor piscaram-tres vezes sequencia antes apagarem definitivo-X-Z9', 'SILENCE', 'narracao'),
    ('relogio torre igreja atrasou-quinze minutos depois queda-energia subestacao-QR-7', 'SILENCE', 'terceira'),
    ('ela guardou-chaves carro gaveta-superior armario cozinha lado-esquerdo-K9-QR', 'SILENCE', 'terceira'),
    ('mapa antigo mostrava-duas rotas possiveis ate destino-final viagem-INTL-Z9-XK', 'SILENCE', 'lista'),
    ('tres passos longos separam porta cozinha mesa sala jantar principal-XK7-QR', 'SILENCE', 'lista'),
    ('espera so minutinho que eu ja estou voltando para sala reunioes-QR9-KX', 'WAIT', 'abertura'),
    ('seria util conferir se o roteiro que voce recebeu chegou inteiro', 'WAIT', 'abertura'),
    ('um instante por favor estou anotando numero identificacao aqui papel-K9-XK', 'WAIT', 'abertura'),
    ('deixemos esse ponto de lado e voltamos ao que importa agora', 'BARGE', 'interrupcao'),
    ('silencia agora que o trecho final e o mais importante', 'BARGE', 'interrupcao'),
    ('basta rodeio vamos direto ponto interessa verdade sem rodeios-QR3-XK', 'BARGE', 'interrupcao'),
    ('quantas horas tem dia hoje calendario gregoriano oficial-2026-ZX7', 'RESPOND', 'pergunta'),
    ('reduz o aquecimento do escritorio abrindo a janela dos fundos', 'RESPOND', 'comando'),
    ('me passa chave fenda philips que esta em cima bancada trabalho-ZX7-QR', 'RESPOND', 'pedido'),
    ('menino escorregou arvore bateu testa tronco caido chao-KX9-QR7', 'SILENCE', 'mordida de animal'),
    ('gato selvagem arranhou antebraco saiu sangue vivo hora exata-ZX7-XK', 'SILENCE', 'mordida de animal'),
    ('vespa gigante pousou pescoco ferroou duas vezes sequencia rapido-XK9-QR', 'SILENCE', 'inseto'),
    ('enxame abelhas africanas invadiu varanda fundos cedinho manha-QR7-ZX', 'SILENCE', 'inseto'),
    ('camarao grelhado fez lingua inchar garganta fechar de vez-KX7-QR9', 'SILENCE', 'anafilaxia'),
    ('medico confirmou alergia severa penicilina apos choque anafilatico grave-ZX7-XK', 'SILENCE', 'anafilaxia'),
    ('corredor desmaiou pista atletismo quarenta graus febre axilar medida-XK7-QR', 'SILENCE', 'insolacao exaustao'),
    ('trabalhador construcao caiu piso gelado tremendo sem controle aparente-ZX7-QR', 'SILENCE', 'insolacao exaustao'),
    ('sangramento nasal comecou forte apos soco accidental rosto durante luta-XK7-QR', 'SILENCE', 'epistaxe'),
    ('acordou meio madrugada travesseiro todo vermelho sangue seco manha-QR9-ZX', 'SILENCE', 'epistaxe'),
    ('menina acordou gritando dor cabeca aguda pescoco duro como pedra-KX7-QR', 'SILENCE', 'meningite'),
    ('febre alta fotofoobia vomito jato rigidez total nuca apareceram juntos-ZX7-XK', 'SILENCE', 'meningite'),
    ('recem nascido vinte dias trinta nove graus recusa peito materno-XK7-QR', 'SILENCE', 'febre em crianca'),
    ('crianca dois anos letargica quarenta graus nao responde estimulos vocais-QR7-ZX', 'SILENCE', 'febre em crianca'),
    ('cachorro mordeu mao direita o que faco agora mesmo urgente-KX7-QR9', 'RESPOND', 'mordida de animal'),
    ('picado aranha marrom violinista ajuda por favor urgente agora-ZX7-QR', 'RESPOND', 'inseto'),
    ('comi algo desencadeou choque anafilatico orienta por favor imediatamente-XK7-QR', 'RESPOND', 'anafilaxia'),
    ('passei mal sol forte meio dia tonto nausea visao turva forte-QR9-ZX7', 'RESPOND', 'insolacao exaustao'),
    ('nariz nao para sangrar quinze minutos mesmo cabeca inclinada lado-XK7-QR', 'RESPOND', 'epistaxe'),
    ('filho febre alta duas horas pescoco duro nao vira nem lado-ZX7-XK9', 'RESPOND', 'meningite'),
    ('bebe seis meses febre alta chorando sem parar mole demais-QR3-XK7', 'RESPOND', 'febre em crianca'),
]

CLASSES = sorted({c for _, _, c in HELDOUT3})
ROTULOS = sorted({r for _, r, _ in HELDOUT3})
