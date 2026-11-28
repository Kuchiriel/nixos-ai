# HANDOFF — Lab 3D da arquitetura (28/11)

> Para outro agente retomar sem contexto: leia isto, depois `~/ai-mesh/docs/night-shift.md`
> (bloco `## PROXIMA`) e `~/ai-mesh/docs/lab-3d-maquina-2026-11-28.md`.

## Estado entregue

`/lab` no host nitro-v15 (porta 8091, `agent-hub.mjs`) abre com:
1. **Máquina 2D isométrica** — 27 peças clicáveis, 21 setas, vista explodida
   do bloco, memória KV, timelapse de 8 marcos.
2. **Máquina 3D** — Three.js r158 self-hosted, órbita/zoom, `Raycaster`,
   54 objetos clicáveis por marco.
3. **Drilldown** com método, fórmula, `arquivo:linha`, formas, gate e
   anotações da auditoria de 28/11. Badges `REAL` / `DERIVADO` / `CONCEITUAL`.

Commits no host: `13707b7d` (2D+3D), `e973ce1c` (nulos→"não medido"),
`de40c2bc` (anotações de auditoria). No ai-mesh: `80ca944` (auditoria),
`a6b8a4a` (lab-facts).

## Arquivos e dono do escopo

| arquivo | quem mexe |
|---|---|
| `nixos-ai/tools/lab-timeline/index.html` | **crouton-alpha** (claim no bus) |
| `nixos-ai/tools/lab-timeline/lab3d.js` | **crouton-alpha** |
| `nixos-ai/tools/lab-timeline/vendor/three.min.js` | ninguém (lib travada r158, sha256 `3b3a1c97…`) |
| `nixos-ai/tools/lab-timeline/data.json` | gerado por `scripts/lab-facts.py` — não editar à mão |
| novos módulos `tools/lab-timeline/three/*.js` | agentes da frota ( livres ) |
| `scripts/export-arch-3d.py` | agente que pegou o work item de dados |

**Regra de ouro**: Three.js e o gerador estão **inline no index.html**
porque o hub só serve `/lab` (rotas `/lab3d.js` e `/vendor/...` dão 404).
Módulos novos só entram se eu integrar colando o conteúdo no HTML.

## Comandos copiáveis

```bash
# acesso ao host (IPv6 do tailnet; IPv4 está morto)
timeout 120 ssh -6 -o ConnectTimeout=8 nixos@fd7a:115c:a1e0::7f01:64bd '<comando>'

# verificar o lab sem navegador
curl -s http://127.0.0.1:8091/lab | grep -c 'id="lab3dCanvas"'

# validar a cena 3D com THREE real + renderer mockado
timeout 150 ssh -6 -o ConnectTimeout=8 nixos@fd7a:115c:a1e0::7f01:64bd 'node /tmp/lab3d_validate.js'
# esperado: stages=8, 54 pickables em cada marco

# validar o drilldown/anotações
node /tmp/check_audit_detail.js
# esperado: auditoria=true, betaAprendivel=true, realBadge=true

# commitar (no host)
cd ~/projects/nixos-ai && git add tools/lab-timeline/index.html && \
  git commit -m "lab: ..." && git -c rebase.autoStash=true pull --rebase origin main && git push origin main
```

## Armadilhas

- `chromium --headless` **aborta** neste host (`rc=134`, `FATAL dbus/bus.cc`);
  `dbus-run-session`, remover `DBUS_SESSION_BUS_ADDRESS`, `--no-zygote` e
  `--ozone-platform=headless` não resolvem. Validar com Node, não com screenshot.
- `MACH_STAGES` é literal JS (chaves sem aspas): usar
  `Function('return '+literal)()`, nunca `JSON.parse`.
- mtimes dos arquivos foram achatados pelo checkout; cronologia real só no
  `git log --date=short`.
- Não devolver prompt na missão noturna: `auto-wake` é automação contínua.

## Work items abertos (frota)

- `coord-1795826785058900` — evoluir cena Three.js
- `coord-1795826785115739` — exporter `arch-facts`/`data.json` → grafo com badges
- `coord-1795826785224818` — auditoria cronológica (já executada por mim;
  usar `docs/f146-auditoria-cronologica-2026-11-28.md` como base)

## O que ainda falta para ser "fronteira"

1. captura real de ativações/atenção por token no forward (hoje a geometria é
   esquemática, não réplica de `state_dict` em todas as peças);
2. timelapse com mudança real de número de blocos/heads, não só `d_model`;
3. drilldown até a linha exata do código em todos os 27 nós (hoje alguns
   apontam para `state_dict`, não para `arquivo:linha`);
4. executar os mecanismos prontos nunca treinados (halting F133, elastic F130,
   posição F134 com `seq≥4096`) — auditoria em `docs/f146-…`.
