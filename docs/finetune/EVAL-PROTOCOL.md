# EVAL PROTOCOL — adapter LoRA (quando COMPLETE)

1. Baixar output: `kaggle kernels output kuchiriel/bonsai-qlora-r8 -p <dir>`
   (adapter safetensors + tokenizer).
2. Converter p/ GGUF: `llama.cpp/convert_lora_to_gguf.py` (venv ou nix).
3. Servir: router atual + `llama-server --lora adapter.gguf` em porta
   separada (NÃO trocar o :8080 produtivo ainda).
4. Bateria (mesmos prompts, n=3): E1 bytes, chain-count, T-fact-181,
   L9-T8 rule+serialize. Comparar c/ base (0/3, 4/5, 5/5, 0/9).
5. Regressão geral: GSM8K-sample (forgetting) + KB-suite.
6. Critério: melhora formato SEM regressão → promove; qualquer
   regressão → arquiva números e reverte. Trade-offs documentados.
