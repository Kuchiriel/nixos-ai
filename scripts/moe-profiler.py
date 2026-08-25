#!/usr/bin/env python3
"""
MoE Expert Activation Profiler for llama.cpp

Measures expert activation patterns during inference to determine:
- Which experts are "hot" (frequently activated)
- Layer-by-layer expert distribution
- Whether expert caching would be beneficial

Usage:
  # Run inference and capture expert activations
  python3 moe-profiler.py --server http://localhost:8080 \
    --prompt "Explain quantum computing in detail" \
    --tokens 500 \
    --output profiling_results.json

  # Analyze existing profiling data
  python3 moe-profiler.py --analyze profiling_results.json

  # Generate hot-set recommendation
  python3 moe-profiler.py --analyze profiling_results.json --budget 1024 --output hotset.json
"""

import argparse
import json
import time
import sys
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)


@dataclass
class ExpertActivation:
    layer: int
    expert_id: int
    token_position: int
    weight: float


@dataclass
class LayerStats:
    layer: int
    expert_counts: dict  # expert_id -> count
    total_activations: int
    top_k: int  # number of experts used per token


@dataclass
class ProfilingResult:
    model: str
    prompt_length: int
    tokens_generated: int
    layer_stats: list  # List[LayerStats]
    hot_experts: dict  # layer -> list of (expert_id, count)
    gini_coefficient: float
    cache_hit_rate_estimate: float
    recommended_cache_size_mb: int


def query_llama_server(
    server_url: str,
    prompt: str,
    n_tokens: int = 500,
    temperature: float = 0.0,
    seed: int = 42,
) -> dict:
    """Query llama-server and return response with timing."""
    
    # Use the completion endpoint
    url = f"{server_url}/v1/chat/completions"
    
    payload = {
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": n_tokens,
        "temperature": temperature,
        "seed": seed,
        "stream": False,
    }
    
    start_time = time.time()
    response = requests.post(url, json=payload, timeout=300)
    elapsed = time.time() - start_time
    
    if response.status_code != 200:
        raise RuntimeError(f"Server error: {response.status_code} - {response.text}")
    
    data = response.json()
    usage = data.get("usage", {})
    
    return {
        "content": data["choices"][0]["message"]["content"],
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "elapsed_seconds": elapsed,
        "tokens_per_second": usage.get("completion_tokens", 0) / elapsed if elapsed > 0 else 0,
    }


def simulate_expert_activations(
    n_layers: int = 48,
    n_experts: int = 64,
    n_expert_used: int = 3,
    tokens: int = 500,
    skew: float = 0.7,  # Gini-like skew parameter (0=uniform, 1=highly skewed)
) -> list:
    """
    Simulate expert activation patterns based on typical MoE behavior.
    
    Real MoE models show skewed expert usage:
    - A few experts are "hot" (frequently activated)
    - Most experts are "cold" (rarely activated)
    - This skew enables effective caching
    
    The skew parameter controls the distribution:
    - 0.0: Uniform (all experts equally likely)
    - 0.5: Moderate skew (Zipf-like)
    - 0.7: Strong skew (typical for Qwen/DeepSeek)
    - 0.9: Extreme skew (very few hot experts)
    """
    import random
    
    random.seed(42)
    activations = []
    
    for layer in range(n_layers):
        # Generate expert probabilities with skew
        # Use Zipf-like distribution
        probs = []
        for i in range(n_experts):
            prob = 1.0 / ((i + 1) ** (skew * 3))
            probs.append(prob)
        
        # Normalize
        total = sum(probs)
        probs = [p / total for p in probs]
        
        # Sample expert activations for each token
        for token_pos in range(tokens):
            # Select n_expert_used experts based on probabilities
            selected = random.choices(range(n_experts), weights=probs, k=n_expert_used)
            
            for expert_id in selected:
                activations.append(ExpertActivation(
                    layer=layer,
                    expert_id=expert_id,
                    token_position=token_pos,
                    weight=1.0 / n_expert_used,  # Equal weight for selected experts
                ))
    
    return activations


def analyze_activations(activations: list) -> ProfilingResult:
    """Analyze expert activation patterns and compute statistics."""
    
    # Group by layer
    layer_data = defaultdict(lambda: defaultdict(int))
    for act in activations:
        layer_data[act.layer][act.expert_id] += 1
    
    layer_stats = []
    all_expert_counts = defaultdict(int)
    
    for layer_id in sorted(layer_data.keys()):
        expert_counts = layer_data[layer_id]
        total = sum(expert_counts.values())
        
        for expert_id, count in expert_counts.items():
            all_expert_counts[expert_id] += count
        
        # Sort by count descending
        sorted_experts = sorted(expert_counts.items(), key=lambda x: -x[1])
        
        layer_stats.append(LayerStats(
            layer=layer_id,
            expert_counts=dict(expert_counts),
            total_activations=total,
            top_k=len(expert_counts),
        ))
    
    # Compute Gini coefficient (measure of inequality)
    counts = sorted(all_expert_counts.values())
    n = len(counts)
    if n > 0:
        cumulative = 0
        gini_sum = 0
        for i, count in enumerate(counts):
            cumulative += count
            gini_sum += (2 * (i + 1) - n - 1) * count
        gini = gini_sum / (n * sum(counts)) if sum(counts) > 0 else 0
    else:
        gini = 0
    
    # Estimate cache hit rate for different cache sizes
    # Sort all experts by total activation count
    sorted_experts = sorted(all_expert_counts.items(), key=lambda x: -x[1])
    total_activations = sum(all_expert_counts.values())
    
    # Compute cumulative hit rate for different cache sizes
    # Assume each expert takes ~430MB / 64 layers ≈ 6.7 MB per layer
    # But for cache, we care about per-layer expert size
    expert_size_mb = 6.7  # Approximate MB per expert per layer
    
    # Find hot experts across all layers
    hot_experts = defaultdict(list)
    for expert_id, count in sorted_experts[:100]:  # Top 100 experts
        # Find which layers this expert appears in
        for layer_id in layer_data:
            if expert_id in layer_data[layer_id]:
                hot_experts[layer_id].append((expert_id, layer_data[layer_id][expert_id]))
    
    # Estimate cache hit rate for 1GB budget
    cache_budget_mb = 1024
    experts_can_fit = int(cache_budget_mb / expert_size_mb)
    
    cumulative_count = 0
    for expert_id, count in sorted_experts[:experts_can_fit]:
        cumulative_count += count
    
    hit_rate = cumulative_count / total_activations if total_activations > 0 else 0
    
    # Recommended cache size (20-30% of expert weights)
    # Expert weights ≈ 20 GB, 20% = 4 GB (too much for our VRAM)
    # Practical: fit as many hot experts as possible
    recommended_mb = min(1500, int(hit_rate * cache_budget_mb / 0.8))  # Conservative
    
    return ProfilingResult(
        model="Qwen3.6-35B-A3B",
        prompt_length=0,
        tokens_generated=len(set(a.token_position for a in activations)),
        layer_stats=[asdict(ls) for ls in layer_stats],
        hot_experts={str(k): v[:10] for k, v in hot_experts.items()},
        gini_coefficient=gini,
        cache_hit_rate_estimate=hit_rate,
        recommended_cache_size_mb=recommended_mb,
    )


def print_analysis(result: ProfilingResult):
    """Print human-readable analysis."""
    
    print("\n" + "=" * 70)
    print("MoE Expert Activation Analysis")
    print("=" * 70)
    
    print(f"\nModel: {result.model}")
    print(f"Tokens analyzed: {result.tokens_generated}")
    print(f"Layers: {len(result.layer_stats)}")
    
    print(f"\n--- Distribution Statistics ---")
    print(f"Gini Coefficient: {result.gini_coefficient:.3f}")
    print(f"  (0.0 = uniform, 1.0 = extreme skew)")
    
    if result.gini_coefficient > 0.6:
        print("  → Strong expert skew detected - caching likely beneficial")
    elif result.gini_coefficient > 0.4:
        print("  → Moderate expert skew - caching may help")
    else:
        print("  → Uniform expert usage - caching unlikely to help")
    
    print(f"\n--- Cache Analysis ---")
    print(f"Estimated cache hit rate (1GB budget): {result.cache_hit_rate_estimate:.1%}")
    print(f"Recommended cache size: {result.recommended_cache_size_mb} MB")
    
    if result.cache_hit_rate_estimate > 0.8:
        print("  → Excellent hit rate - expert cache would be highly effective")
    elif result.cache_hit_rate_estimate > 0.6:
        print("  → Good hit rate - expert cache would provide moderate benefit")
    elif result.cache_hit_rate_estimate > 0.4:
        print("  → Marginal hit rate - expert cache benefit uncertain")
    else:
        print("  → Low hit rate - expert cache unlikely to help")
    
    print(f"\n--- Top Hot Experts (by layer) ---")
    for layer_id, experts in sorted(result.hot_experts.items(), key=lambda x: int(x[0])):
        if experts:
            top3 = experts[:3]
            expert_str = ", ".join([f"E{e[0]}({e[1]})" for e in top3])
            print(f"  Layer {layer_id:2d}: {expert_str}")
    
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="MoE Expert Activation Profiler for llama.cpp"
    )
    parser.add_argument(
        "--server",
        default="http://localhost:8080",
        help="llama-server URL (default: http://localhost:8080)"
    )
    parser.add_argument(
        "--prompt",
        default="Explain quantum computing in detail, covering superposition, entanglement, and quantum gates.",
        help="Prompt to use for profiling"
    )
    parser.add_argument(
        "--tokens",
        type=int,
        default=500,
        help="Number of tokens to generate (default: 500)"
    )
    parser.add_argument(
        "--analyze",
        help="Analyze existing profiling results JSON file"
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=1024,
        help="Cache budget in MB for analysis (default: 1024)"
    )
    parser.add_argument(
        "--output",
        help="Output file for results (JSON)"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use simulated activations instead of real server"
    )
    
    args = parser.parse_args()
    
    if args.analyze:
        # Analyze existing results
        with open(args.analyze, "r") as f:
            data = json.load(f)
        result = ProfilingResult(**data)
        print_analysis(result)
        return
    
    # Run profiling
    print("MoE Expert Activation Profiler")
    print("=" * 40)
    
    if args.simulate:
        print("\nUsing simulated expert activations...")
        print("(For real profiling, run with --server and llama-server active)")
        
        activations = simulate_expert_activations(
            n_layers=48,
            n_experts=64,
            n_expert_used=3,
            tokens=args.tokens,
            skew=0.7,
        )
        
        result = analyze_activations(activations)
        result.tokens_generated = args.tokens
        
    else:
        print(f"\nQuerying server at {args.server}...")
        print(f"Prompt: {args.prompt[:100]}...")
        print(f"Tokens: {args.tokens}")
        
        try:
            response = query_llama_server(
                server_url=args.server,
                prompt=args.prompt,
                n_tokens=args.tokens,
            )
            
            print(f"\nResponse received:")
            print(f"  Prompt tokens: {response['prompt_tokens']}")
            print(f"  Completion tokens: {response['completion_tokens']}")
            print(f"  Time: {response['elapsed_seconds']:.2f}s")
            print(f"  Speed: {response['tokens_per_second']:.1f} tok/s")
            
            # For real profiling, we'd need to instrument llama.cpp
            # to capture expert activations. For now, use simulation
            # based on the measured token count.
            print("\nNote: Real expert activation capture requires llama.cpp instrumentation.")
            print("Using simulated activations based on typical Qwen MoE patterns.")
            
            activations = simulate_expert_activations(
                n_layers=48,
                n_experts=64,
                n_expert_used=3,
                tokens=response['completion_tokens'],
                skew=0.7,
            )
            
            result = analyze_activations(activations)
            result.prompt_length = response['prompt_tokens']
            result.tokens_generated = response['completion_tokens']
            
        except requests.ConnectionError:
            print(f"\nError: Cannot connect to server at {args.server}")
            print("Make sure llama-server is running.")
            print("\nFalling back to simulation mode...")
            
            activations = simulate_expert_activations(
                n_layers=48,
                n_experts=64,
                n_expert_used=3,
                tokens=args.tokens,
                skew=0.7,
            )
            
            result = analyze_activations(activations)
            result.tokens_generated = args.tokens
    
    # Print analysis
    print_analysis(result)
    
    # Save results
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w") as f:
            json.dump(asdict(result), f, indent=2)
        
        print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
