# Harness compartilhado — como usar o JARVIS de outra máquina (07/11/2026)

> Pedido do dono: *"combinar expor tools jarvis para uso dele como rag, memory e
> tudo que for util que temos ou até ajudar eles criarem uma versão deles"*.

## 1. O que existe agora (medido, não desenhado)

**Servidor novo:** `modules/ai/jarvis/src/jarvis/jarvis_http.py` — o JARVIS
(RAG + memória + lições + vault) servido em **MCP `streamable-http`** ⇒
alcança agentes de **outras máquinas** (o MCP stdio do JARVIS é local só).

**Prova de execução** (07/11, real, não "deve funcionar"):
- `build_server()` ⇒ **10 tools** registradas: `jarvis_rag_search`,
  `jarvis_rag_index`, `jarvis_remember`, `jarvis_recall`, `jarvis_lessons`,
  `jarvis_vault_list`, `jarvis_vault_search_obsidian`, `jarvis_vault_write`,
  `jarvis_nix_search`, `jarvis_web_search`.
- `POST /mcp` com `initialize` ⇒ **handshake OK** (`serverInfo: jarvis-knowledge` ✓).
- `tools/list` ⇒ as 10 tools ✓.
- `tools/call` com `jarvis_lessons` ⇒ **resposta real** (lições do banco ✓).

**Zero duplicação:** cada tool chama o **dispatcher central** `mcp_server.call_tool(name, args)`
⇒ uma mudança no `core/` vale para os **dois** servidores (stdio + HTTP) ✓.

## 2. Como uma lane usa (qualquer máquina da tailnet)

```jsonc
// ~/.config/opencode/opencode.json  (ou o equivalente da sua lane)
{
  "mcp": {
    "jarvis-knowledge": {
      "type": "remote",
      "url": "http://100.121.100.103:8766/mcp",
      "enabled": true
    }
  }
}
```

As tools aparecem como `jarvis-knowledge_jarvis_rag_search` (prefixo do server
key) — ou renomeie o server key para `jarvis` pra usar os mesmos nomes de antes ✓.

**Ou, sem MCP:** o mesmo conjunto está no **CLI** (mesmo env, mesma lógica ✓):
```bash
nixos-ai/scripts/jarvis-cli.sh rag "minha query"
nixos-ai/scripts/jarvis-cli.sh remember "o que aprendi"
nixos-ai/scripts/jarvis-cli.sh lessons "o erro que vou repetir"
```

## 3. O que **não** é exposto (decisão de segurança)

Ficam **só no servidor stdio** (local): `human_input` (mouse/teclado do dono),
`game`, `observe_screen`, `browser`, `execute` ⇒ uma lane remota **não** mexe
no desktop do dono sem querer ✓.

⚠️ **Autenticação:** o FastMCP **remove o header `Authorization`** antes de
chegar nas tools (medido em 05/11 no `coord-mcp` ⇒ já é o comportamento
conhecido do stack) ⇒ **não dá para exigir senha no FastMCP**. A proteção é:
**bind no IP do tailnet** (NÃO `0.0.0.0`) + a **ACL do Tailscale** (só a tailnet
chega) ✓. ⇒ **não exponha o JARVIS HTTP fora da tailnet** ✓.

## 4. Se a sua lane quiser a SUA versão

O padrão está no `coord_http.py` (mesma técnica, conjunto menor ✓):
1. um módulo `*_http.py` que faz `FastMCP(...)` + `@mcp.tool` por tool;
2. cada tool chama o `core/` (nunca reimplementa ✓);
3. a unit do home-manager sobe com o **IP do tailnet** como host ✓;
4. a lane aponta o MCP remoto pra ela ✓.
O skill `mcp-development` tem o passo-a-passo ✓.

## 5. Quem usa o quê (a lacuna que o dono mandou fechar)

- **JARVIS (nixos-ai)** ⇒ RAG (code/memories/books) ✓ · memória ✓ · lições ✓ ·
  vault ✓ · web search ✓ · nix ✓.
- **Cervo (jarvis@nitro-v15, redteam/matrix)** ⇒ já usa `jarvis_rag_*` ✓ e
  `jarvis_rehydrate` ✓; reportou que a lacuna era **não usar** em algumas
  Tasks ⇒ a regra da raiz agora manda usar ✓.
- **matheus-perf (Windows)** ⇒ em auditoria (falta confirmar ✓).
- **crouton-alpha (Termux)** ⇒ a confirmar ✓.
- **Onca (eu)** ⇒ RAG ✓ antes de grep ✓ · `remember` no fim ✓ · `lessons`
  depois de falha ✓.

> 🔴 **O que NÃO fica no RAG/memória:** segredo (só o **nome** ✓) · dado pessoal
> do dono ✓ · valor de chave ✓. E **toda** medida que muda o comportamento de
> alguém vai também para o `AGENTS.md` do repo da lane ✓ (a memória é efêmera;
> o AGENTS.md é a regra permanente ✓).
