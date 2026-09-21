# RESPONSIBILITY BOUNDARY (Ciclo 8)

MODEL-GENERATION-LIMIT: whitespace misto/blanks/newline-final/CRLF
(F6/F7/F8/F9); tab-adjacente-unicode (CPRO). Bonsai-specific (sem
referência — NIM tentado 6×, timeout; BLOCKED honesto).
PRESENTATION-LIMIT: decorações do read ("N | ", "# header") vazam no
loop (TR-F4/F13 falham no loop, passam no probe). GENERAL (tool-design).
PROTOCOL/TOOL/FS: inocentados (disk==arg 100%).
TASK-DESIGN-LIMIT: pedir reprodução total quando str_replace resolve
(6/6) — divisão correta: modelo especifica OPERAÇÃO, tool preserva bytes.
COMPOSITION-LIMIT: regra-em-loop (T8 0/9 vs probe 3/3).
Modelo: decidir, especificar operação, spans pequenos exatos.
Harness: preservar bytes, validar, verificar, fatos. NUNCA: regenerar
ou reparar bytes pelo modelo quando primitiva determinística existe.
