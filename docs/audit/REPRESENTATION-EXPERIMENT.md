# REPRESENTATION (Ciclo 8 — A-G, n=2)

Literal-tricky 0/2, escaped 2/2, JSON-string 0/2, hex 2/2, base64 2/2,
numbered 0/2, len+content 0/2. Modelo EMITE hex/base64 perfeitamente —
mas SEM decoder no runtime (não construir p/ benchmark: sem evidência
de que decode+uso funcionaria em loop, e structured-edit já resolve
sem codificação). Representação muda geração (escaped ✓) mas o
problema real está no loop (TR-F4/F13). Nenhum decoder adicionado.
