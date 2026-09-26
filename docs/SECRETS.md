# Segredos — onde mora cada chave (leia antes de instalar)

> **Regra de ouro: segredo nunca entra no git.** Nenhum arquivo abaixo é
> commitado (todos em `/etc`, `chmod 600`, fora do repo). Os modelos
> `.example` desta pasta SÃO commitáveis (placeholders).

## Mapa

| Segredo | Arquivo (criar à mão) | Permissão | Quem lê | Como conseguir |
|---|---|---|---|---|
| API keys p/ fallback remoto | `/etc/litellm.env` | `600` | serviços LLM | `GROQ_API_KEY=` ([console.groq.com](https://console.groq.com)) · `GEMINI_API_KEY=` ([aistudio.google.com](https://aistudio.google.com)) — ver `litellm.env.example` |
| Bot do Telegram | `/etc/jarvis-telegram.env` | `600` | `jarvis-telegram` | fale com [@BotFather](https://t.me/BotFather): `/newbot` → token; teu chat id via [@userinfobot](https://t.me/userinfobot) — ver `jarvis-telegram.env.example` |
| Chaves do opencode (nuvem opcional) | `~/.local/share/opencode/auth.json` | `600` | opencode | **automático**: `opencode-auth-sync.sh` copia do env (`GROQ_API_KEY`, `GEMINI_API_KEY`...) no login — não edite à mão |
| Git/GitHub (push) | `~/.ssh/` + `gh` | `600`/`700` | git, `gh` | `ssh-keygen -t ed25519 -C "voce@maquina"` → cola a `.pub` em GitHub → Settings → SSH keys; depois `gh auth login` |
| Webhooks/pagamentos (se usar) | painéis dos provedores | — | — | Yampi/Supabase/Make: valores SÓ nos dashboards, nomes em `docs/OPERACAO.md` quando houver |

## Modelos (copie e preencha)

```bash
sudo cp docs/secrets-templates/litellm.env.example /etc/litellm.env
sudo cp docs/secrets-templates/jarvis-telegram.env.example /etc/jarvis-telegram.env
sudo chmod 600 /etc/litellm.env /etc/jarvis-telegram.env
sudoedit /etc/litellm.env   # troque os placeholders
```

## Sem chave, o que funciona?

Tudo local (router, RAG, memória, voz, REPL, bateria) funciona **sem
nenhuma key**. Só o fallback remoto (cascata p/ Groq/Gemini) e o Telegram
precisam dos arquivos acima — sem eles, esses dois degradam com aviso,
o resto nem percebe.
