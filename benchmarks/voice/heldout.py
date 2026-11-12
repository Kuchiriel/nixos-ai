# Held-out PT-BR utterances rotuladas a mao (expert) — ZERO overlap com os
# templates do gen-lora-data.py (que gerava os 1.180 exemplos de treino).
# Semantics: RESPOND = pedido direto/enunciao completo ao assistente;
# SILENCE = backchannel/ruido OU fala completa NAO dirigida ao assistente
# (TV, monologo, ambiente); WAIT = incompleta; BARGE = interrupcao/correcao.
HELDOUT = [
    # ── RESPOND (pedido enderecado, sem "Jarvis" obrigatorio) ─────────
    ("acende a luz da copa", "RESPOND"),
    ("desliga o ventilador do quarto", "RESPOND"),
    ("me diz que horas da reuniao", "RESPOND"),
    ("toca uma bossa nova", "RESPOND"),
    ("abre o youtube no meu pc", "RESPOND"),
    ("quanto esta o dolar hoje", "RESPOND"),
    ("me lembra de ligar pro dentista amanha de manha", "RESPOND"),
    ("qual e a previsao do tempo para sabado", "RESPOND"),
    ("pega a nota fiscal do mes passado", "RESPOND"),
    ("muda o volume da cozinha pra quarenta", "RESPOND"),
    ("grava isso que eu acabei de falar", "RESPOND"),
    ("explica rapidinho o que e gradient clipping", "RESPOND"),
    ("quero um resumo do que aconteceu hoje", "RESPOND"),
    ("chama o lula pra passeio", "RESPOND"),
    ("sobe a calefacao pra vinte e dois graus", "RESPOND"),
    ("anota na lista de compras leite e cafe", "RESPOND"),
    # ── SILENCE (backchannel, midia, ambiente — NAO dirigido) ─────────
    ("ai meu deus que historia essa", "SILENCE"),
    ("o prefeito anunciou novas medidas ontem", "SILENCE"),
    ("ela nasceu em sao paulo em mil novecentos e oitenta", "SILENCE"),
    ("que bonito esse jogo de ontem", "SILENCE"),
    ("hum", "SILENCE"),
    ("aham", "SILENCE"),
    ("ta bom entao", "SILENCE"),
    ("olha so que coisa", "SILENCE"),
    ("isso e verdade mesmo", "SILENCE"),
    ("onde voce estuda", "SILENCE"),  # conteudo de TV (pergunta retorica da midia)
    ("qual era o nome do ator principal", "SILENCE"),  # TV
    ("virgula dois pontos e travessao", "SILENCE"),  # audio de edicao/legenda
    ("por exemplo se um quadrado mede dez centimetros", "SILENCE"),  # aula
    ("tem uma cena no final que explica tudo", "SILENCE"),  # comentario sobre filme
    ("a taxa de juros subiu nesta semana", "SILENCE"),  # noticia
    ("nos proximos minutos vamos ver", "SILENCE"),  # programete
    # ── WAIT (incompleta — mais fala vem) ─────────────────────────────
    ("entao deixa eu te explicar uma coisa", "WAIT"),
    ("eu tava pensando em", "WAIT"),
    ("sabe quando voce vai na padaria e", "WAIT"),
    ("a questao e que o arquivo", "WAIT"),
    ("quando eu era pequeno eu", "WAIT"),
    ("o problema e que", "WAIT"),
    ("me fala uma coisa", "WAIT"),
    ("olha so o que aconteceu comigo hoje", "WAIT"),
    ("eu nao sei se devia", "WAIT"),
    ("voce viu aquilo que", "WAIT"),
    ("pra comecar eu acho que", "WAIT"),
    ("o negocio e o seguinte", "WAIT"),
    ("calma que eu ja explico", "WAIT"),
    # ── BARGE (interrompe/corrige o assistente) ───────────────────────
    ("nao nao e isso", "BARGE"),
    ("pera deixa eu ver", "BARGE"),
    ("para", "BARGE"),
    ("calma calma", "BARGE"),
    ("nao isso ta errado", "BARGE"),
    ("deixa eu te falar uma coisa", "BARGE"),
    ("para com isso", "BARGE"),
]
