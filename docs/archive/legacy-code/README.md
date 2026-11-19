# Legacy code (arquivado)

Scripts sem consumidores, movidos aqui para preservar histórico sem poluir
`src/jarvis/core/`. Nenhum foi apagado; use `git log --follow <arquivo>` para
reconstruction.

| arquivo | origem | motivo |
|---|---|---|
| `make_laya_notebook.py` | `core/` (7d687a53, 2026-08) | export ONNX/cell do fine-tune Laya; 0 imports e 0 artefatos no repo |
| `build_laya_dataset.py` | `core/` (4a87309c, 2026-08) | dataset difficulty-classifier Laya; 0 imports e 0 artefatos |

Se o fine-tune Laya voltar, restaurar com `git mv` inverso — não reescrever.
