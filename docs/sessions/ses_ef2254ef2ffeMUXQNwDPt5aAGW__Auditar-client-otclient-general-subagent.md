# Auditar client otclient (@general subagent)

- **sessão:** `ses_ef2254ef2ffeMUXQNwDPt5aAGW`
- **quando:** 2026-10-05 20:56 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 109 (exportadas: 25)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Audite o CLIENT em `/home/nixos/projects/otclient/` (OTClient Redemption 4.x dev, x64, protocolo 1525; 187 arquivos C++, 247 Lua, 42 arquivos uncommitted no git).

PASSO 1 OBRIGATORIO: escreva `EM_ANDAMENTO` em `/home/nixos/projects/plans/audit-05-10/04-client.md`.
PASSO 2: investigue. PASSO 3: reescreva com o relatorio.

REGRA ABSOLUTA: **NAO BUILDAR, NAO COMPILAR, NAO RODAR O CLIENT.** O dono foi explicito: o binario em uso vem de um launcher rofi e build novo quebra o fluxo dele. Apenas leitura, grep e git.

FOCAS:

1. **DIAGNOSTICO PRINCIPAL — janelas nao abrem.** Sintoma: entra no mundo (HP 155/155, mana 60/60, actionbar, minimapa, chat, grade de botoes), mas menus/inventario/skills NAO abrem; tela fica "limpa".
   Investigue de onde pode vir:
   - `modules/game_interface/gameinterface.lua` esta MODIFICADO e nao commitado. Leia o diff (`git diff modules/game_interface/gameinterface.lua`). Adiciona widget? Pode estar quebrando a construicao das janelas?
   - Como o OTUI reage a `image-source` quebrado: **silencia ou lanca erro?** Isso e decisivo. Procure em `src/client/uisprite.cpp`, `src/framework/graphics/`, e no parser de .otui (`src/framework/ui/ui*.cpp`, ou `src/client/otui*.cpp` / `uiloader`). Um `.otui` malformado faz o modulo inteiro falhar silenciosamente?
   - Existe um teste pronto: `verificarJanelas()` em `otclient-autotest.lua` (procura 9 janelas e loga existe/stylesheet/show/visivel). Leia e explique como rodar SEM buildar.
   - Cruze: os 10 arquivos `data/styles/*.otui` modificados — algum tem sintaxe que quebra o parser de OTUI?

2. **Debt de git.** `git status --short` tem 42 entradas. Classifique: o que e trabalho real do dono (nao tocar), o que e lixo/debug temporario (removivel), o que e RISCO (meio aplicado). Aponte especialmente: `data/images/blackfun/` (pack do dono), `data/otui-merge-test/` (pasta de teste temporaria), logs dentro do repo.

3. **O parser de skills 0xA1.** `src/client/protocolgameparse.cpp` tem `parsePlayerSkills` com log repetindo `ERROU (unread=N)` + `bloco OK ate 90 skills`. Analise a logica de parsing: ha bug de bound ou de contagem? O `total` esta sendo lido do lugar certo? Custo de substr por byte no loop (perf)?

4. **Rede.** `src/framework/net/connection.cpp` tem um fix meu para IP literal (bypass de `async_resolve`). Revise com olhar critico: o timer foi armado na posicao certa? A corrida e' realmente eliminada? Comment o que esta em risco.

5. **UI/performance geral.** Busca no update loop, redesenho de widget, `recursiveGetChildById`, alocacao por frame. Achados com evidencia.

6. **Oportunidades de UI.** `data/images/` tem 240 arquivos em `ui/`, 35 em `topbuttons/`, 27 em `inventory/`, 22 em `bars/`. Ache duplicacao/conflito real (o mesmo arquivo referenciado com nome/path diferente? dois estilos定义indo o mesmo widget?).

REGRAS:
- So leitura/grep/git. Nada de build, nada de executar o client, nada de pkill, nada de docker.
- CONFIRME relendo contexto. Marque "HIPOTESE" se nao tiver certeza. Nao reporte speculation como achado.

FORMATO (PT-BR, markdown):
- VEREDITO: tabela de severidade.
- ACHADOS (ordenado por severidade, com `arquivo:linha`, impacto, correcao).
- DIAGNOSTICO DAS JANELAS: hipoteses ordenadas + como testar cada uma.
- DEBT DE GIT: tabela do que tocar / nao tocar.
- VERIFICADO-OK.
- LIMITACOES.

Mensagem final: 15 linhas, contagem por severidade + causa mais provavel das janelas nao abrirem.

---

## · ?

I'll start by writing the EM_ANDAMENTO marker, then investigate.

---

## · ?

Marker written. Now investigating.

---

## · ?

`data/styles/*.otui` não está modificado — premissa incorreta. Vou checar os candidatos reais que quebram **todas** as janelas.

---

## · ?

Encontrei algo forte em `uiminiwindow.lua`. Vou verificar `onGeometryChange` no C++.

---

## · ?

CONFIRMADO: `30-miniwindow.otui` **não tem** `rightResizeBorder`. Vou verificar a assinatura e quem herda UIMiniWindow.

---

## · ?

Esta é a parte decisiva (FOCA 1). Vou ler o `uimanager.cpp` no ponto de parse do OTUI.

---

## · ?

Achado crítico em `uimanager.cpp:764-769`. Agora o comportamento de `image-source` quebrado.

---

## · ?

Hipótese forte: geometria salva. Vou checar `otclientrc.lua` e o `conf/` novo.

---

## · ?

Duas minas: `client_styles/styles.lua` importa .otui, e existe um `otclient.log` no repo. Vou ler os dois.

---

## · ?

`otclient.log` de hoje 17:54 prova que o login funciona e os estilos importam. Agora o monkey-patch que intercepta **todo** `loadUI`:

---

## · ?

O fix documenta **exatamente** o sintoma. Vou validar se `g_resources.fileExists` existe como binding Lua.

---

## · ?

Muito promissor. Vou achar o arquivo de settings salvo e ler as posições.

---

## · ?

`init.lua:168` carrega settings de `/config.otml`. Vou achar o arquivo físico e ler a geometria salva.

---

## · ?

**Achei o arquivo de settings.** Vou ler a geometria salva das janelas.

---

## · ?

**Smoking gun**: `window-size: 941 504` + `hudScale: 2`, e `skillWindow` salvo com `height: 544` em `y=100`. Vou cruzar.

---

## · ?

Diagnóstico principal fechado. Agora FOCA 6 (imagens) e o inventário do debt

---

## · ?

**Achado crítico.** `30-miniwindow.otui` (commitado) depende de imagens **untracked**. Vou confirmar.

---

## · ?

Contradição — vou verificar se `data/styles/` está rastreado.

---

## · ?

**Achado P0 de git**: os arquivos modificados não aparecem no `git status`. Vou verificar flags.

---

## · ?

**Bug concreto encontrado.** `toggle()` do inventário dereferencia `iconTopMenu`, que é nil no modo normal.

---

## · ?

**Achei o caminho do "não abre sem erro".** Vou confirmar `findContentPanelAvailable`.

---

## · ?

Últimos dados para a tabela de debt, e escrevo o relatório.

---

## · ?

Investigação completa. Escrevendo o relatório.

---

## · ?

Relatório em `plans/audit-05-10/04-client.md`. Nada foi buildado, executado ou modificado no repo.

**Placar: 3 P0 · 5 P1 · 8 P2 · 4 P3** (20 achados)

**Causa mais provável das janelas não abrirem — três bugs somados, todos confirmados por leitura:**
1. **Inventário (P0):** `inventory.lua:539` — `toggle()` dereferencia `iconTopMenu`, que é `nil` no modo normal (`extendedView(false)` destrói o botão, `gameinterface.lua:2200` chama com `false`). Erro a cada clique.
2. **Skills (P0):** `skills.lua:1286` — `findContentPanelAvailable` devolve `nil` (porque `gameSelectedPanel` só é setado por clique do usuário, `gameinterface.lua:1870`), e o `return` é **mudo**: botão faz nada, sem log.
3. **Geometria (P1):** `config.otml` tem `window-size 941×504` + `hudScale 2` → boot aplica `setHUDScale(1.5)` → UI lógica vira **627×336**, mas `skillWindow` está salva com `height: 544` em `y=100`. Não cabe.

**Refutei a hipótese do dono:** o `gameinterface.lua` +179 **não** quebra a construção de janelas (bloco inteiro dentro de `if useThing`, só roda em right-click).

**Resposta decisiva sobre OTUI:** `image-source` quebrado é **100% silencioso** (`uiwidgetimage.cpp:229-230`, sem log; sem `width/height` explícito o widget fica 0×0). `.otui` malformado **não** é silencioso — mata o módulo inteiro via `loadUI → nullptr` + `g_logger.error`. Erro de propriedade de style (inclusive `!text:` avaliado como Lua) é engolido em `traceError` (`uiwidget.cpp:742`).

**Dois riscos que valem decisão sua:** `data/images/blackfun/` (untracked) é referenciado por 3 arquivos *tracked* — `30-miniwindow.otui:5` é o fundo de toda miniwindow; e `result` (symlink Nix) não está no `.gitignore`, então `git add -A` commita build output.

**Teste pronto sem build:** `touch /tmp/opencode/otc-autotest && ./run.sh` — usa `./result/bin/otclient` (store de 01/10), não compila nada; log em `/tmp/opencode/client-live.log`, probe em `otclient-autotest.lua:203-240`. **Atenção:** o binário é de 01/10, então ele testa LUA/OTUI/config, não as mudanças de C++.

**Premissas do enunciado corrigidas:** não são 42 entradas (36: 19 `M` + 17 `??`) nem 10 arquivos em `data/styles/*.otui` (são 3). Duas HIPÓTESES permanecem abertas: a imagem do `blackfun` quebrar, e a ordem invertida `setupOnStart()` antes de `refresh()` em `onGameStart`.

---

