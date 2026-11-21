# Incidente de Push Protection (21/11)

## O que aconteceu

O push de 723 commits locais foi bloqueado pelo GitHub Push Protection:
detecções de chaves em commits **antigos** (`f49d66a`, `f7eb040`) dentro de
`docs/sessions/ses_f3151b…md` e `ses_f0d36…md`. Tipos detectados (sem valores):
Resend API Key, Supabase Personal Access Token, GCP API Key, OpenRouter API Key,
Groq API Key. O diff dos commits novos tinha **0** marcadores — o bloqueio era
histórico, não desta mudança.

## Decisão e ação

`d0012 = Unblock` (decisão do dono). Não reescrevi histórico (§10.4). Criei
bypasses via API oficial:

```
gh api -X POST repos/Kuchiriel/nixos-ai/secret-scanning/push-protection-bypasses \
  -f reason=will_fix_later -f placeholder_id=<id>
```

O GitHub revela placeholders progressivamente; o loop coletou 11 IDs das
mensagens de erro e criou um bypass para cada um, sem imprimir valores.
`git push origin main` terminou rc=0: `LOCAL = origin/main = f0ef2576`,
divergência 0.

## Risco residual

As chaves **continuam no histórico Git** (bypass não apaga nada). Recomenda-se
rotação dessas credenciais nos respectivos provedores e, só depois, limpeza do
histórico com coordenação — nenhuma das duas ações foi feita sem autorização
específica. Os bypasses têm validade curta (~1 h), mas cobrem os commits já
enviados; commits futuros não contêm os marcadores.
