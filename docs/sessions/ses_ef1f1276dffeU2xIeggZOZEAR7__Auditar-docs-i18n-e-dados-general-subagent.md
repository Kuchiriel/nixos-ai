# Auditar docs, i18n e dados (@general subagent)

- **sessão:** `ses_ef1f1276dffeU2xIeggZOZEAR7`
- **quando:** 2026-10-05 21:53 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 195 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Audite DADOS, DOCUMENTACAO e DERIVA (drift) entre docs e disco em `/home/nixos/projects/canary-official/`.

PASSO 1 OBRIGATORIO: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/06-docs-dados.md`.
PASSO 2: investigue. PASSO 3: reescreva com o relatorio.

CONTEXTO: existe `AGENTS.md` na raiz que diz que o "Project Map" esta DESATUALIZADO e manda usar `docs/architecture/SYSTEM-MAP.md`. Verifique se essahierarquia de docs esta healthy ou se ha doc conflicting. Alem disso ha `data-sandbox/docs/` com ~10 docs criados por agentes diferentes.

FOCAS:

1. **Drift doc vs disco.** Pegue `docs/architecture/SYSTEM-MAP.md`, `docs/improvements/INDEX.md`, `AGENTS.md`, e os docs em `data-sandbox/docs/`. Para cada claim concreto (caminho, porta, numero de arquivo, comando), VERIFIQUE no disco. Liste o que esta errado. Exemplo do tipo de coisa a checar: "Sistema X esta em src/Y" quando Y nao existe; "porta 8080 e o jarvis" quando mudou; doc que descreve um arquivo que foi movido/deletado. Seja especifico: doc, linha do doc, e o que o disco mostra.

2. **Estado do pipeline i18n.** `tools/i18n/` (13 scripts) e `dataset/i18n/` (17 JSON). O pipeline esta funcional ou abandonado? Roda de ponta a ponta? Qual o ultimo output real (data do arquivo mais recente)? Ha dados FAKE/placeholder nos JSON (procure string tipo "TODO", "xxx", "Lorem", nome de item em ingles onde deveria estar pt-br, gerado automaticamente)? Amostre e quantify: de `item-name.json` (1.3M), que % das entradas parecem realmente traduzidas vs herdadas do ingles?

3. **Estado do pipeline de mapa.** `dataset/maps/` (21 arquivos) e `/home/nixos/projects/rme` (clone separado). Roda? Os JSON (`sprites_rme.json`, `doodads_rme.json`) estao atualizados em relacao ao RME? Lembrando: ja sabemos que `rme/data/materials/brushs/doodads.xml:7301` e `grounds.xml:1153` tem `&` cru (XML invalido) — isso foi consertado? Os geradores depends desses XML? Se depende, o mapa gerado esta errado? (ja sabemos que o mapa gerado e' OTBM valido e nao depende desses XML, mas CONFIRME).

4. **Escala do repositorio.** `data-sandbox/` tem 362 MB. O que pesa? Ha artefato que deveria estar fora (log, state gerado em runtime dentro do repo)? `find` por arquivo grande e por `*.lua` de state. Cite tamanho e caminho. Isso e' higiene de repo.

5. **Codeigo morto em docs/scripts.** Ha script em `tools/` ou `dataset/` que nao e' chamado por nada? Ha doc orfao? Quantifique: conte script .py/.sh e quantos sao referenciados por outro arquivo ou por doc.

6. **Dataset/ui-assets** (37 MB, seis packs de imagem baixados) e `dataset/PixelkilnUIForge_FreeSample_v1_4.zip` (300K) — ainda estao zipados em `dataset/`? O zip do Pixelkiln foi extraido E o zip ficou? Limpeza recomendada.

REGRAS:
- So leitura. NAO modifique nada. NAO rode gerador que escreva arquivo. NAO build.
- Pode rodar `python3 -c` para ANALISAR json (read-only). NAO pode reescrever.
- Cite `arquivo:linha` e numeros concretos.
- Numeros, nao adjetivos.

FORMATO (PT-BR, markdown):
- VEREDITO: tabela de severidade.
- DRIFT DOC vs DISCO: tabela (doc:linha -> o que diz -> o que o disco mostra).
- I18N: numeros reais de cobertura e traducao.
- MAPAS: estado real.
- HIGIENE: tabela de artefato -> tamanho -> acao.
- SCRIPT ORFAO: lista.
- VERIFICADO-OK.
- LIMITACOES.

Mensagem final: 15 linhas, quantos docs com drift + numeros do i18n + tamanho de lixo no repo.

---

## · ?

Relatório em `/home/nixos/projects/plans/audit-05-10/06-docs-dados.md`.

**Docs com drift: 22** (de 121 `.md` no repo) + a hierarquia da raiz da monorepo, que é o achado mais grave: `SYSTEM-MAP.md:16` erra 5 de 6 números de §1 (1798→2112 arquivos, 18→42 `.git` aninhados, 7→19 gitlinks), diz que `docs/` da raiz está vazio (tem 26 arquivos — é ele mesmo), e descreve um diretório `~/` que não existe mais; `INDEX.md` se contradiz na própria seção de contagem.

Pior drift individual: `data-sandbox/docs/AUDITORIA-2026-10-03.md:47-56` descreve um patch de sprites em 10 itemtypes **552xx que não existem** em `data/items/items.xml` (max 55018) nem no `.dat` (max 54266), e cita um `patch_dat_donors.py` inexistente. Os 5 docs de handoff mais o `COORDENACAO.md` erram contagens (177 e 269 testes vs 366 reais; "6 mounts" vs 11; "119 refs" vs 26), e `HANDOFF-2026-10-05.md:3` — o único ponto de entrada — manda ler um `vault/PENDENTES-SESSAO-0510.md` que não existe.

**I18N: 14.685 de 16.109 strings extraíveis (91%), mas qualidade ruim.** `item-name.json` tem 8.833 entradas, 200 (2,3%) com `pt==en`, 21,3% com escore PT-BR baixo, e 100% de origem `ia-local` (zero curadoria humana). O juiz adversarial reprova 1.885 (21,3%) e **373 das 8.845 entradas acabaram em `Connection refused :8092`** — o pipeline parou no meio; as portas8110 e 8092 estão fechadas agora. 5 campos do manifesto (`mount`, `outfit`, `storage`, `attachedeffect`, `group` = 389 strings) nunca geraram arquivo. O `i18n_ptbr.lua` gerado (953 KB, 15.853 entradas) **não tem consumidor nenhum** — falta o patch C++.

**Mapas: o `&` cru não foi consertado** — segue em `dataset/rme/brushs/doodads.xml:7301` e `grounds.xml:1153` (cópia do clone), e `ET.parse()` falha nos dois. Mas **CONFIRMADO que não afeta o mapa**: o gerador usa regex, não XML; `extrair_quebraveis.py` extrai 8.015 ids normalmente, e `gerar_otbm.py` não lê XML nenhum. Já os `*_rme.json` estão stale (01/10 vs scripts de 05/10) e documentam o RME 10.80, não o clone.

**Lixo no repo: ~350 MB** de 705 MB — `canary.otbm` duplicado byte-a-byte do `otservbr.otbm` (176 MB commitados), `RPG Effect All Free.zip` 63 MB nunca extraído, 7 zips de assets já extraídos (11,6 MB), 20 backups `.bak-*` (92 MB) + `.sawbak` (4,6 MB), 3 binários de build na raiz, e 3 arquivos `.lua` de state de runtime dentro de `data-sandbox/lib/sandbox/`. Repo com 125 untracked e 56 modificados. Bônus: `run_tests.lua` é não-determinístico — 2 de 3 execuções falham por um roll de 10% sem semente em `forno.lua:247`.

Nada foi modificado: `git status` segue em 181 entradas, idêntico ao início.

---

