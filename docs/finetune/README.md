# docs/finetune — dataset próprio p/ futuro treino (21/09)

- successes.jsonl: 113 runs world_ok (SFT-chosen).
- failures.jsonl: 74 runs falhas c/ classe+evidência+usabilidade.
- outputs.jsonl: 91 artefatos c/ verdade por path + subclasse do erro.
- VIABILITY.md: estudo (base unpacked, --lora deploy, VRAM, opções).
- Quota Kaggle: INTACTA (nada rodado). Segredos: só em /etc/litellm.env,
  nunca aqui.
- Próximo (P1): emparelhar chosen↔rejected por task (pares preferência).
