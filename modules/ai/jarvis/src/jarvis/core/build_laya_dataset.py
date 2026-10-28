#!/usr/bin/env python3
"""
Monta dataset de fine-tuning do Laya (difficulty classifier) para JARVIS.

Fontes:
1. Prompts reais dos dev-sessions (~32 únicos, path-stripped)
2. Prompts sintéticos PT+EN diversificados (cobrem o espectro)

Rotula com o classificador atual (regex + Laya como weak labeler).
Split 70/15/15 train/calib/test. Formato p/ notebook Kaggle Laya.

Uso:
    python3 -m jarvis.core.build_laya_dataset --out /tmp/laya-dataset
    python3 -m jarvis.core.build_laya_dataset --synth-only --count 400
"""

import argparse
import json
import random
import re
from pathlib import Path


def _strip_paths(text: str) -> str:
    text = re.sub(r"/tmp/[^\s\"']+", "PATH", text)
    return re.sub(r"\s+", " ", text).strip()


def load_real_prompts(state_dir: str = "/home/nixos/.local/state/jarvis") -> list[str]:
    """Extrai prompts únicos dos dev-sessions JARVIS."""
    import glob

    prompts: set[str] = set()
    for fp in glob.glob(f"{state_dir}/dev-session-*.json"):
        try:
            data = json.loads(Path(fp).read_text())
            for m in data.get("messages", []):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    c = _strip_paths(m["content"])
                    if len(c) > 5:
                        prompts.add(c)
        except Exception:
            pass
    return sorted(prompts)


# ── Prompts sintéticos por categoria (PT + EN) ──────────────────────────
# Cada tupla: (prompt, difficulty_label)
# Label vem do julgamento humano (weak supervision); o classificador atual
# serve como baseline a ser batido pelo fine-tune.

_SIMPLE = [
    ("What is 2+2?", "simple"),
    ("ola, tudo bem?", "simple"),
    ("Good morning, how are you today?", "simple"),
    ("List the files in the current directory", "simple"),
    ("liste os arquivos do projeto", "simple"),
    ("What time is it?", "simple"),
    ("que horas são?", "simple"),
    ("Translate 'good morning' to Spanish", "simple"),
    ("traduza 'bom dia' para inglês", "simple"),
    ("Define the word 'ephemeral'", "simple"),
    ("defina a palavra 'efêmero'", "simple"),
    ("Show me the system status", "simple"),
    ("exiba o status do sistema", "simple"),
    ("Is the server running?", "simple"),
    ("o servidor está no ar?", "simple"),
    ("Delete the temporary file /tmp/test.txt", "simple"),
    ("remova o arquivo temporário", "simple"),
    ("Copy file A to folder B", "simple"),
    ("copie o arquivo A para a pasta B", "simple"),
    ("Rename main.py to app.py", "simple"),
    ("renomeie main.py para app.py", "simple"),
    ("What is the capital of France?", "simple"),
    ("qual é a capital do Brasil?", "simple"),
    ("Print the current date", "simple"),
    ("imprima a data de hoje", "simple"),
    ("How many lines are in this file?", "simple"),
    ("quantas linhas tem este arquivo?", "simple"),
    ("Create an empty file called done.txt", "simple"),
    ("crie um arquivo vazio chamado done.txt", "simple"),
    ("Check if port 8080 is open", "simple"),
    ("verifique se a porta 8080 está aberta", "simple"),
    ("Say OK", "simple"),
    ("diga apenas ok", "simple"),
    ("What version of Python is installed?", "simple"),
    ("qual versão do Python está instalada?", "simple"),
    ("List running docker containers", "simple"),
    ("liste os containers docker em execução", "simple"),
    ("Show disk usage", "simple"),
    ("mostre o uso de disco", "simple"),
    ("Read the first 10 lines of README.md", "simple"),
    ("leia as primeiras 10 linhas do README", "simple"),
    ("Convert 100 celsius to fahrenheit", "simple"),
    ("converta 100 fahrenheit para celsius", "simple"),
    ("What does HTTP 404 mean?", "simple"),
    ("o que significa HTTP 500?", "simple"),
    ("List environment variables", "simple"),
    ("liste as variáveis de ambiente", "simple"),
    ("Check git status", "simple"),
    ("verifique o status do git", "simple"),
    ("Show me the last 5 commits", "simple"),
    ("mostre os últimos 5 commits", "simple"),
    ("What is the file permission of config.json?", "simple"),
    ("qual é a permissão do arquivo config.json?", "simple"),
]

_MODERATE = [
    ("Explain how TCP handshake works in detail", "moderate"),
    ("explique como funciona o handshake TCP", "moderate"),
    ("Write a regex to match Brazilian phone numbers", "moderate"),
    ("escreva um regex para validar email", "moderate"),
    ("Fix this bug: the loop exits early when index is out of range", "moderate"),
    ("conserte este bug: a função retorna None às vezes", "moderate"),
    ("Summarize this article in 3 bullet points", "moderate"),
    ("resuma este artigo em 3 tópicos", "moderate"),
    ("Draft a professional email declining a meeting invite", "moderate"),
    ("redija um email profissional agradecendo o convite", "moderate"),
    ("Add unit tests for the calculate_total function", "moderate"),
    ("adicione testes unitários para a função calcular_total", "moderate"),
    ("Refactor this function to use list comprehension", "moderate"),
    ("refatore esta função para usar list comprehension", "moderate"),
    ("Explain the difference between REST and GraphQL", "moderate"),
    ("explique a diferença entre SQL e NoSQL", "moderate"),
    ("Convert this JSON to CSV format", "moderate"),
    ("converta este CSV para formato JSON", "moderate"),
    ("Debug why this Python script throws KeyError", "moderate"),
    ("depure por que este script Python lança IndexError", "moderate"),
    ("Write a function to flatten a nested dictionary", "moderate"),
    ("escreva uma função para achatar um dicionário aninhado", "moderate"),
    ("Optimize this SQL query for better performance", "moderate"),
    ("otimize esta query SQL para melhor performance", "moderate"),
    ("Implement pagination for this API endpoint", "moderate"),
    ("implemente paginação para este endpoint de API", "moderate"),
    ("Translate this paragraph to technical English", "moderate"),
    ("traduza este parágrafo para português técnico", "moderate"),
    ("Compare the pros and cons of PostgreSQL vs MySQL", "moderate"),
    ("compare os prós e contras de Python vs JavaScript", "moderate"),
    ("Write a script to batch rename files with a pattern", "moderate"),
    ("escreva um script para renomear arquivos em lote", "moderate"),
    ("Add error handling to this API call", "moderate"),
    ("adicione tratamento de erros nesta chamada de API", "moderate"),
    ("Explain the observer design pattern with a code example", "moderate"),
    ("explique o padrão observer com um exemplo de código", "moderate"),
    ("Migrate this function from callbacks to async/await", "moderate"),
    ("migre esta função de callbacks para async/await", "moderate"),
    ("Write a Python one-liner to count word frequency", "moderate"),
    ("escreva um one-liner Python para contar frequência de palavras", "moderate"),
    ("Set up a CI pipeline that runs tests on every push", "moderate"),
    ("configure um pipeline CI que rode testes a cada push", "moderate"),
    ("Refactor the config to use environment variables", "moderate"),
    ("refatore o config para usar variáveis de ambiente", "moderate"),
    ("Write documentation for the public API methods", "moderate"),
    ("escreva documentação para os métodos públicos da API", "moderate"),
    ("Create a Dockerfile for this Node.js app", "moderate"),
    ("crie um Dockerfile para esta aplicação Python", "moderate"),
    ("Explain how garbage collection works in Go", "moderate"),
    ("explique como funciona o garbage collection em Java", "moderate"),
    ("Add rate limiting to this Express endpoint", "moderate"),
    ("adicione rate limiting a este endpoint Flask", "moderate"),
    ("Write a migration script for the database schema change", "moderate"),
    ("escreva um script de migração para a mudança de schema", "moderate"),
    ("Debug the memory leak in this long-running process", "moderate"),
    ("depure o vazamento de memória neste processo de longa duração", "moderate"),
]

_HARD = [
    ("Design a distributed consensus protocol using Raft with fault tolerance for 5 nodes", "hard"),
    ("projete um protocolo de consenso distribuído com tolerância a falhas", "hard"),
    ("Refactor this monolithic service into microservices with event sourcing and CQRS", "hard"),
    ("refatore este monólito em microserviços com event sourcing", "hard"),
    ("Analyze the time complexity of this recursive algorithm and prove correctness", "hard"),
    ("analise a complexidade temporal deste algoritmo recursivo e prove a correção", "hard"),
    ("Implement a custom garbage collector with generational collection", "hard"),
    ("implemente um garbage collector customizado com coleta generacional", "hard"),
    ("Design a type system with inference for a mini programming language", "hard"),
    ("projete um sistema de tipos com inferência para uma mini linguagem", "hard"),
    ("Write a compiler front-end with lexer, parser, and AST for a DSL", "hard"),
    ("escreva um front-end de compilador com lexer, parser e AST para uma DSL", "hard"),
    ("Architect a real-time collaborative editor with operational transformation", "hard"),
    ("arquitete um editor colaborativo em tempo real com transformação operacional", "hard"),
    ("Prove the halting problem reduction and explain each step", "hard"),
    ("prove a redução do problema da parada e explique cada passo", "hard"),
    ("Design a sharded consistent hashing ring with virtual nodes for a distributed cache", "hard"),
    ("projete um anel de hash consistente com sharding e nós virtuais", "hard"),
    ("Implement a B-tree from scratch with insert, delete, and rebalancing", "hard"),
    ("implemente uma B-tree do zero com inserção, remoção e rebalanceamento", "hard"),
    ("Analyze race conditions in this concurrent code and propose a lock-free solution", "hard"),
    ("analise race conditions neste código concorrente e proponha solução lock-free", "hard"),
    ("Design a schema for a multi-tenant SaaS with row-level security", "hard"),
    ("projete um schema multi-tenant SaaS com segurança em nível de linha", "hard"),
    ("Write a formal specification for this protocol using TLA+", "hard"),
    ("escreva uma especificação formal deste protocolo usando TLA+", "hard"),
    ("Optimize this deep learning training loop for multi-GPU with gradient accumulation", "hard"),
    ("otimize este loop de treinamento deep learning para multi-GPU", "hard"),
    ("Design an adversarial robustness evaluation framework for NLP models", "hard"),
    ("projete um framework de avaliação de robustez adversarial para modelos NLP", "hard"),
    ("Implement a vector database index with HNSW graph from scratch", "hard"),
    ("implemente um índice de banco vetorial com grafo HNSW do zero", "hard"),
    ("Analyze the CAP theorem trade-offs for this specific system design", "hard"),
    ("analise os trade-offs do teorema CAP para este design de sistema", "hard"),
    ("Design a consensus algorithm that achieves both linearizability and availability", "hard"),
    ("projete um algoritmo de consenso que alcance linearizabilidade e disponibilidade", "hard"),
    ("Write a static analyzer that detects SQL injection patterns in Python code", "hard"),
    ("escreva um analisador estático que detecte padrões de SQL injection em Python", "hard"),
    ("Implement a lock-free concurrent hash map with memory reclamation", "hard"),
    ("implemente um hash map concorrente lock-free com reclamation de memória", "hard"),
    ("Design a cost-aware query optimizer for a federated database system", "hard"),
    ("projete um otimizador de consultas com awareness de custo para banco federado", "hard"),
    ("Prove termination of this recursive function using a well-founded ordering", "hard"),
    ("prove a terminação desta função recursiva usando ordem bem-fundada", "hard"),
    ("Architect an event-driven microservice mesh with saga pattern for distributed transactions", "hard"),
    ("arquitete um mesh de microserviços event-driven com padrão saga", "hard"),
    ("Implement a Byzantine fault tolerant voting protocol for 12 nodes", "hard"),
    ("implemente um protocolo de votação BFT para 12 nós", "hard"),
    ("Design a formal grammar and type checker for a dependently-typed language subset", "hard"),
    ("projete uma gramática formal e type checker para um subconjunto de linguagem dependente de tipos", "hard"),
    ("Analyze the spectral properties of this graph and determine community structure", "hard"),
    ("analise as propriedades espectrais deste grafo e determine a estrutura de comunidades", "hard"),
    ("Write a just-in-time compiler strategy for a dynamically-typed language", "hard"),
    ("escreva uma estratégia de compilador JIT para uma linguagem dinamicamente tipada", "hard"),
]


def synthesize(count: int = 400, seed: int = 42) -> list[tuple[str, str]]:
    """Gera dataset sintético balanceado PT+EN."""
    rng = random.Random(seed)
    pool = _SIMPLE + _MODERATE + _HARD
    # Repete até atingir count, com jitter leve pra variar
    out = []
    while len(out) < count:
        prompt, label = rng.choice(pool)
        # Jitter: às vezes adiciona contexto extra
        if rng.random() < 0.3:
            suffixes = [
                " Be concise.",
                " Responda em português.",
                " Use best practices.",
                " Include examples.",
                " Keep it under 100 words.",
                " Prioritize correctness.",
            ]
            prompt = prompt + rng.choice(suffixes)
        out.append((prompt, label))
    return out[:count]


def build_dataset(
    real_prompts: list[str],
    synth: list[tuple[str, str]],
) -> list[dict]:
    """Combina real + sintético, rotula com classificador atual (weak label)."""
    from jarvis.core.model_policy import classify_difficulty

    samples: list[dict] = []

    # Sintético: label humano é ground truth
    for prompt, label in synth:
        samples.append({
            "state": prompt,
            "question": "How difficult is this request for a small local language model?",
            "options": {
                "simple": "greetings, short factual questions, lookups, yes/no, formatting",
                "moderate": "code explanation, multi-step, moderate reasoning, drafting, summarizing",
                "hard": "complex reasoning, architecture, debugging multi-file, proofs, creative, long context",
            },
            "answer": label,
        })

    # Real: fraco label com classificador atual
    for prompt in real_prompts:
        if len(prompt) < 10:
            continue
        weak = classify_difficulty(prompt)
        samples.append({
            "state": prompt[:2000],
            "question": "How difficult is this request for a small local language model?",
            "options": {
                "simple": "greetings, short factual questions, lookups, yes/no, formatting",
                "moderate": "code explanation, multi-step, moderate reasoning, drafting, summarizing",
                "hard": "complex reasoning, architecture, debugging multi-file, proofs, creative, long context",
            },
            "answer": weak,
        })

    return samples


def split_dataset(
    samples: list[dict],
    train_ratio: float = 0.70,
    calib_ratio: float = 0.15,
    seed: int = 42,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split 70/15/15 stratificado por answer."""
    rng = random.Random(seed)
    by_label: dict[str, list[dict]] = {}
    for s in samples:
        by_label.setdefault(s["answer"], []).append(s)

    train, calib, test = [], [], []
    for label, group in by_label.items():
        rng.shuffle(group)
        n = len(group)
        n_train = int(n * train_ratio)
        n_calib = int(n * calib_ratio)
        train.extend(group[:n_train])
        calib.extend(group[n_train:n_train + n_calib])
        test.extend(group[n_train + n_calib:])

    rng.shuffle(train)
    rng.shuffle(calib)
    rng.shuffle(test)
    return train, calib, test


def save_kaggle_format(
    samples: list[dict],
    path: Path,
) -> None:
    """Salva no formato que o notebook Laya Kaggle espera."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Laya fine-tuning dataset")
    parser.add_argument("--out", default="/tmp/laya-dataset", help="Output dir")
    parser.add_argument("--count", type=int, default=400, help="Synthetic count")
    parser.add_argument("--synth-only", action="store_true", help="Skip real prompts")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    out = Path(args.out)
    real = [] if args.synth_only else load_real_prompts()
    synth = synthesize(args.count, args.seed)
    samples = build_dataset(real, synth)
    train, calib, test = split_dataset(samples, seed=args.seed)

    save_kaggle_format(train, out / "train.jsonl")
    save_kaggle_format(calib, out / "calibration.jsonl")
    save_kaggle_format(test, out / "test.jsonl")

    # Stats
    from collections import Counter
    dist = Counter(s["answer"] for s in samples)
    print(f"Dataset: {len(samples)} samples ({len(real)} real + {len(synth)} synth)")
    print(f"Distribution: {dict(dist)}")
    print(f"Splits: train={len(train)} calib={len(calib)} test={len(test)}")
    print(f"Saved to: {out}/")


if __name__ == "__main__":
    main()
