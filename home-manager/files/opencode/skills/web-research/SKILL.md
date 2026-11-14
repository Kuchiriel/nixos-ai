---
name: web-research
description: "Use when reading or acting on a web page: prefer agent-browser (text DOM, 1.9 s) over the owner's GUI browser, which is heavy and takes the screen. Tavily/web_search for pure search, jarvis_browser only when the session must be the owner's own logged-in window."
license: MIT
---

# Pesquisa e leitura de página web

A casa tem três caminhos para a web, e eles não são intercambiáveis. Escolha pelo
critério de custo, não por hábito.

## 1. agent-browser (o padrão para ler e agir)

CLI nativo (Rust) que dá um navegador ao agente e devolve a **árvore de
acessibilidade em texto**, com `ref` em cada elemento interativo. Medido em
14/11 nesta casa: `open` + `snapshot` de uma página real do GitHub em **1,85 s**.

```bash
nix run nixpkgs#agent-browser -- open "https://exemplo.com"
nix run nixpkgs#agent-browser -- snapshot -i      # elementos interativos, com ref
nix run nixpkgs#agent-browser -- click @e12
nix run nixpkgs#agent-browser -- fill @e3 "texto"
```

Vantagens sobre o browser do dono: **não rouba a tela** (que é o custo real do
computer use), devolve texto (não screenshot, que é o que o modelo gasta token
lendo), e é headless (não depende do Hyprland, então funciona em qualquer
contexto, inclusive em container).

Limites: não tem sessão do dono (login do Google, do banco, do GitHub autenticado
**não** vem junto), e o snapshot é da árvore de acessibilidade (um site que não
expõe a árvore aparece vazio). Nesse caso, caia no 3.

## 2. Tavily / web_search (só busca)

Para achar a página, não para navegar nela: é mais barato e mais rápido. Traz o
texto já extraído, e é o caminho certo para "qual a documentação de X" e "o que
mudou em Y".

## 3. jarvis_browser (o browser do dono, com a mão dele)

Só quando a sessão **precisa** ser a janela do dono com o login dele (o AGENTS.md
é explícito: o browser do dono audita ouvindo e **nunca** deve mutar). É o mais
lento (screenshot a cada passo) e o único que bloqueia a tela.

## Regra de bolso

- Ler ou agir numa página: **agent-browser**.
- Achar a página: **Tavily / web_search**.
- Precisa do login do dono: **jarvis_browser**, e nada de mutar.
