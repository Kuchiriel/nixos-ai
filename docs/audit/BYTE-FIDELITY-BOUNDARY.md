# BYTE-FIDELITY BOUNDARY (Ciclo 8 — matriz F1-F17, n=2)

PASS exato (geração isolada): F1 ASCII, F2 multi-espaço, F3 leading,
F4 trailing, F5 tab-único, F10/F11/F12 unicode, F13 tool-format, F14 JSON,
F15 shell, F16 markdown, F17 pipes (13/17).
FAIL: F6 mixed (espaço+tab → "a b"), F7 blanks (\n\n\n→\n\n),
F8 newline-final (some), F9 CRLF 1/2.
Representações: escaped/hex/base64 2/2; literal-tricky/JSON-str/
numbered/len-prefix 0/2.
Superfície real de falha: whitespace MISTO/REPETIDO de kinds diferentes
+ blank lines + newline-final. Tab/space/unicode isolados: OK.
Runner: /tmp/c8/probes.py. Status: VERIFIED (geração).
