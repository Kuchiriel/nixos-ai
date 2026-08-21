curl -s http://127.0.0.1:8080/completion \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "'"$(python3 -c "print('O rápido raposa marrom pula sobre o cão preguiçoso. ' * 60)")"'\n\nResuma o texto acima em uma frase.",
    "n_predict": 128,
    "cache_prompt": false,
    "temperature": 0,
    "ignore_eos": true
  }' | python3 -c "import json,sys; d=json.load(sys.stdin)['timings']; print(json.dumps(d, indent=2))"
