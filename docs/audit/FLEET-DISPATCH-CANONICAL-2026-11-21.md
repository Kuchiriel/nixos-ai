# `fleet-dispatch` — aplicação pós-A/B (21/11)

Aprovado pelo A/B 3/3 (`docs/fleet-dispatch-ab-result-2026-11-21.md` no
ai-mesh). Canonico: **implementação Python do host**
`scripts/fleet-dispatch.py` (`~/bin/fleet-dispatch` é symlink para ele).

## Ajustes aplicados no host

- Modo do arquivo versionado corrigido de `100644` para `100755`: o symlink em
  `~/bin` era 777, mas o alvo 644 impedia execução direta (`Permissão negada`).
  `/usr/bin/env` **existe** — o diagnóstico anterior estava errado e foi
  corrigido em `ARMADILHAS.md`.
- Rastro para `jobs-audit`: `~/.local/state/job-fleet-dispatch.trace` escrito
  no início de `main()`.
- `publicar_bus()` agora recebe `projeto` explicitamente (antes referenciava
  uma variável local de `main()`, que geraria `NameError` após wake/claim).
  Payload verificado: `{"kind":"status","agent":"fleet-dispatch","lane":"frota","project":"frota",...}`.
- Política de bus: o dispatcher publica `kind=status` no despacho; o texto da
  tarefa agora pede ao agente **uma** linha `kind=done` ao terminar — sem
  duplicar o mesmo evento.

## Shim no celular

`~/bin/fleet-dispatch` passou a ser shim: tenta o host por IPv6 do tailnet e
depois pela LAN, chamando `python3 .../scripts/fleet-dispatch.py "$@"`.
Grava também o trace local (`job-fleet-dispatch.trace`) para o jobs-audit do
celular. O Bash antigo foi **arquivado** com sha `94637d7724ff…` e manifesto em
`~/work/hub/backups/2026-11-21/` — nada apagado.

## Validação

- A/B rerodado com o host corrigido: 3/3 decisões iguais (fila vazia; item
  `AB-1` + `Onca` idle com wake/claim; apenas `spawn9` idle → sem agente).
- `~/bin/fleet-dispatch --dry-run` via shim → `(fila frota vazia — sem tarefas
  DISCOVERED/READY)` e trace local gravado.
- `jobs-audit`: job 116 com trace fresco (0 min).
- Hub `/api/state` 200; nenhum serviço reiniciado.

Commit do host: `85191621`.
