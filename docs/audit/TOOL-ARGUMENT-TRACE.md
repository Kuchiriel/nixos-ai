# TOOL-ARGUMENT TRACE (Ciclo 8 — primeira divergência)

SOURCE → ARG → RESULT → DISK capturados (n=2):
- TR-F5: arg==disk==source 2/2 (tab-único sobrevive ao loop).
- TR-F4: arg='trail' (stripped!) — probe passava; loop corrompe no ARG.
- TR-F13: arg='1 | 1 | data' (decoração duplicada); disk==arg.
- CP duplicate: modelo escolheu write_file (não cp!), arg==disk 2/2.
- CPRO (bytes limpos no prompt): arg corrompe igual (tab→espaço).
- SR/M2/M6: f.txt correto 6/6 (avaliador checou o.txt errado — bug meu,
  corrigido na leitura; str_replace é byte-fiel!).
VEREDITO: disk==arg em 100% medido → protocol/tool/FS INOCENTES.
Primeira divergência = ARGUMENTO DO MODELO (geração ou contaminação
da observação). Runner: /tmp/c8/arms.py.
