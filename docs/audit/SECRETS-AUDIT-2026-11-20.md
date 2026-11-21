# Auditoria de segredos na configuração declarada (20/11)

Escopo: árvore Nix versionada (126 arquivos, 243 lidos), histórico Git completo
desses arquivos, 32 gerações do home-manager no `/nix/store` (329 alvos únicos
após resolver symlinks) e os 9 arquivos do `/etc` da geração atual do sistema.
**Somente leitura.** Nenhum valor de credencial é registrado neste documento:
achados são identificados por caminho, linha, classe e fingerprint SHA-256
(12 hex). Nenhuma chave foi rotacionada e nenhum histórico foi reescrito.

## Metodologia

Scanner determinístico com padrões para `sk-`, `gh[pousr]_`, `gsk_`, `AIza`,
`xox[…]-`, `Bearer`, URL com `user:pass@`, chave privada PEM e atribuições
`api_key|token|secret|password|credential|webhook = "…"`. Cada linha também é
classificada como **referência** (agenix/sops/`builtins.readFile`/`${…}`) ou
**literal**. Placeholders claros são descartados. Nenhum valor é impresso.

## Resultado

| superfície | varredura | literais | tokens reais |
|---|---|---:|---:|
| Nix no HEAD | 243 arquivos | 5 únicos | **0** |
| histórico Git (`*.nix`) | 3,48 MB de patch | 18 únicos | **0** |
| `/nix/store` (32 gerações) | 329 alvos resolvidos | 6 ocorrências | **0** |
| `/etc` da geração atual | 9 arquivos | 0 | **0** |

Os 5 literais do HEAD são placeholders: `home.nix:876` (`sk-` de 8 chars,
`openai-api-base` apontando para `localhost:8080`, fingerprint `1eaa840f0577`)
e 4 `api_key` em `modules/services/litellm-cascade.nix` (16/23/25/29 chars,
todos legíveis por humano, sem dígitos e sem prefixo de provider; fingerprints
`f41fbc55150e`, `70f07b34a3c4`, `2b0cbdd105f4`, `db8709daa926`).
O módulo é alcançável por `hosts/nitro-v15/configuration.nix`.

As 5 ocorrências no `/nix/store` são o mesmo placeholder do aider em gerações
diferentes. O outro sinal (`sk-` + 20 letras, 5 linhas de um `fontconfig.conf`)
foi **falso positivo confirmado**: o contexto redigido mostrou
`sk-home-manager-path` como sufixo de um caminho `/nix/store/…-home-manager-path`.

Os 18 valores históricos são todos `wordlike` e sem dígitos; o único com
prefixo `sk-` é o placeholder de 8 chars acima. Não há evidência de token real
em nenhum commit.

## Risco registrado (P2)

Placeholders de `api_key` são gravados como texto literal na configuração e,
portanto, também no Nix Store (world-readable, imutável). Hoje não são
segredos, mas o padrão facilita que uma chave real seja colada no mesmo ponto
e vire permanente no histórico Git e no Store. Recomendação: migrar esses
cinco pontos para referência de segredo (agenix/sops já usados em
`nv-gate.nix`, `rclone-sync.nix`) ou env no runtime, **com rebuild autorizado
pelo dono**. Não alterado nesta sessão (escopo era auditoria; §10.5).

## Critério de sucesso

Nenhum valor de credencial real encontrado → **não há rotação nem reescrita de
histórico a fazer**. Risco de padrão registrado em `TECHNICAL-DEBT.md` (P2).

## Reverificação por delta (21/11)

A auditoria completa não foi repetida: não houve mudança que a justificasse.
Medido em `c80279e8`: `git diff --name-only 5480d1f3..HEAD -- "*.nix"` →
**0 arquivos**; árvore de trabalho sem `.nix` modificado; número de gerações
home-manager no `/nix/store` segue **32**. Logo o veredito anterior permanece:
0 tokens reais, risco P2 dos placeholders literais inalterado. Nenhuma chave
foi rotacionada e nenhum histórico reescrito.
