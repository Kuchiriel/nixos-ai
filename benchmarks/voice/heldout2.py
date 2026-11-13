"""Held-out #2: items written fresh on 2026-11-12 (never in train/eval corpora).

These target the v3 failure classes, phrased differently from bench items:
SILENCE broadcast declaratives, SILENCE list scaffolding, SILENCE enum intros,
WAIT openings that look like commands/questions, plus BARGE/WAIT contrasts.
Ground truth by hand again. No example ever used elsewhere in this repo.
"""

HELDOUT2 = [
    # SILENCE — broadcast/narration declaratives (news style)
    ("a prefeitura anunciou a nova ponte de acesso hoje", "SILENCE"),
    ("os cientistas publicaram o resultado na revista Nature", "SILENCE"),
    ("a companhia aérea cancelou os voos de hoje cedo", "SILENCE"),
    ("a estiagem prejudicou a safra no norte do estado", "SILENCE"),
    ("os músicos apresentaram a sinfonia no concerto de abertura", "SILENCE"),
    ("a exposição de fotografia abre no sábado no museu", "SILENCE"),
    # SILENCE — narration/description, no addressee
    ("ele cresceu no interior perto do rio Araguaia", "SILENCE"),
    ("as navegações chegaram ao Brasil no século dezesseis", "SILENCE"),
    ("os carros elétricos estão ficando mais acessíveis a cada ano", "SILENCE"),
    ("a novela das nove volta na segunda com horário estendido", "SILENCE"),
    # SILENCE — list scaffolding / unit intros
    ("por exemplo um triângulo retângulo tem um ângulo de noventa graus", "SILENCE"),
    ("por exemplo um pentágono regular tem cinco lados iguais", "SILENCE"),
    ("nas próximas aulas vamos estudar a colonização portuguesa", "SILENCE"),
    ("neste capítulo vamos ver os verbos irregulares", "SILENCE"),
    ("os próximos parágrafos detalham o argumento central", "SILENCE"),
    ("as reticências indicam interrupção da fala", "SILENCE"),
    # SILENCE — enumeration scaffolding
    ("os dois pontos introduzem uma explicação", "SILENCE"),
    ("os parênteses isolam um comentário secundário do autor", "SILENCE"),
    # WAIT — openings that look like questions/commands (enumeration launches)
    ("sabe o que aconteceu comigo hoje", "WAIT"),
    ("escuta só o que aconteceu comigo", "WAIT"),
    ("deixa eu te contar uma coisa importante", "WAIT"),
    ("fala aí uma coisa pra mim", "WAIT"),
    # BARGE — genuine interruption
    ("para para para chega já", "BARGE"),
    ("chega de conversa vamos ao fato", "BARGE"),
]
