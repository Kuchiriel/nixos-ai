#!/usr/bin/env python3
"""
Gera notebook Kaggle de fine-tuning do Laya pro dataset JARVIS (difficulty).

Adapta o recipe oficial (NandhaKishorM/laya notebooks/laya_finetune_*_kaggle)
pro nosso dataset JSONL (state/question/options/answer).

Uso:
    python3 -m jarvis.core.make_laya_notebook \
        --dataset /tmp/laya-dataset --out /tmp/laya_finetune_jarvis.ipynb
"""

import argparse
import json
from pathlib import Path


def build_notebook(dataset_dir: str) -> dict:
    """Constrói notebook Kaggle adaptado pro dataset JARVIS."""

    cells = []

    # [0] Header
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "# Fine-Tuning Laya on JARVIS Difficulty Dataset (Kaggle GPU T4)\n",
            "\n",
            "Adaptado do recipe oficial (`NandhaKishorM/laya` notebooks).\n",
            "\n",
            "**Dataset:** prompts reais JARVIS + sintéticos PT+EN, rotulados\n",
            "simple/moderate/hard para roteamento local↔cloud.\n",
            "\n",
            "**Baseline (Laya base):** 58.8% no test split (simple 90%, mod 60%, hard 27%).\n",
            "**Meta pós fine-tune:** 85%+ overall, hard 70%+.\n",
            "\n",
            "Opções do notebook: Accelerator = GPU T4 (1 é suficiente p/ dataset pequeno),\n",
            "Internet = On."
        ]
    })

    # [1] Install
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "!pip install -q -U \"laya>=0.1.6\" \"transformers>=4.48.0\" \"datasets>=3.0.0\" safetensors huggingface_hub pyarrow pandas scipy accelerate tabulate\n",
            "import laya, transformers, torch\n",
            "print(\"Laya:\", laya.__version__, \"| Transformers:\", transformers.__version__, \"| Torch:\", torch.__version__)\n",
            "print(\"CUDA:\", torch.cuda.is_available(), \"| GPUs:\", torch.cuda.device_count())"
        ]
    })

    # [2] Upload dataset + convert to HF format
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 1. Dataset\n",
            "\n",
            "Faz upload dos 3 JSONLs (train/calibration/test) como Kaggle Dataset\n",
            "ou copia de um caminho. Converte pro formato HF que `items_from_rows` espera."
        ]
    })
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import os, json\n",
            "from pathlib import Path\n",
            "\n",
            "# ── CONFIG: ajuste o caminho p/ onde estão os JSONLs ──\n",
            "# Opção A: Kaggle Dataset (adicione como Input no notebook)\n",
            "DATASET_DIR = \"/kaggle/input/laya-jarvis-dataset\"  # ou o path do seu upload\n",
            "# Opção B: upload manual (arraste os arquivos pra /kaggle/working)\n",
            "if not Path(DATASET_DIR).exists():\n",
            "    DATASET_DIR = \"/kaggle/working\"\n",
            "\n",
            "def load_jsonl(p):\n",
            "    return [json.loads(l) for l in open(p) if l.strip()]\n",
            "\n",
            "train_rows = load_jsonl(f\"{DATASET_DIR}/train.jsonl\")\n",
            "calib_rows = load_jsonl(f\"{DATASET_DIR}/calibration.jsonl\")\n",
            "test_rows = load_jsonl(f\"{DATASET_DIR}/test.jsonl\")\n",
            "print(f\"train={len(train_rows)} calib={len(calib_rows)} test={len(test_rows)}\")\n",
            "\n",
            "# Converte pro formato HF (state/questions/gold como JSON strings)\n",
            "# Formato questions: [{\"type\": \"choice\", \"id\": \"q0\", \"question\": ..., \"options\": [{\"id\": \"simple\", \"description\": ...}]}]\n",
            "# Formato gold: [{\"question_id\": \"q0\", \"choice\": \"simple\"}]\n",
            "def to_hf_row(sample, idx):\n",
            "    options_list = [{\"id\": k, \"description\": v} for k, v in sample[\"options\"].items()]\n",
            "    questions = [{\n",
            "        \"type\": \"choice\",\n",
            "        \"id\": \"q0\",\n",
            "        \"question\": sample[\"question\"],\n",
            "        \"options\": options_list,\n",
            "    }]\n",
            "    gold = [{\"question_id\": \"q0\", \"choice\": sample[\"answer\"]}]\n",
            "    return {\n",
            "        \"id\": f\"jarvis-{idx}\",\n",
            "        \"workflow\": \"jarvis-difficulty\",\n",
            "        \"state\": json.dumps(sample[\"state\"]),\n",
            "        \"questions\": json.dumps(questions),\n",
            "        \"gold\": json.dumps(gold),\n",
            "    }\n",
            "\n",
            "hf_train = [to_hf_row(s, i) for i, s in enumerate(train_rows)]\n",
            "hf_test = [to_hf_row(s, i) for i, s in enumerate(test_rows)]\n",
            "print(f\"HF train={len(hf_train)} test={len(hf_test)}\")\n",
            "print(\"Sample:\", json.dumps(hf_train[0], ensure_ascii=False)[:300])"
        ]
    })

    # [3] Preprocess
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 2. Preprocess\n",
            "\n",
            "Tokeniza e cacheia os items de treino."
        ]
    })
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import os, json, torch\n",
            "from transformers import AutoTokenizer\n",
            "from huggingface_hub import snapshot_download\n",
            "from laya.agent import _fix_tokenizer_config\n",
            "from laya.train import items_from_rows\n",
            "\n",
            "MODEL_ID = \"convaiinnovations/laya\"\n",
            "model_dir = snapshot_download(MODEL_ID)\n",
            "_fix_tokenizer_config(model_dir)\n",
            "\n",
            "tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, \"tokenizer\"))\n",
            "with open(os.path.join(model_dir, \"rl_agent_config.json\")) as f:\n",
            "    cfg = json.load(f)\n",
            "\n",
            "# Converte hf_train p/ rows com state/questions/gold como dicts\n",
            "rows = []\n",
            "for row in hf_train:\n",
            "    rows.append({\n",
            "        \"state\": json.loads(row[\"state\"]),\n",
            "        \"questions\": json.loads(row[\"questions\"]),\n",
            "        \"gold\": json.loads(row[\"gold\"]),\n",
            "    })\n",
            "\n",
            "items, skipped = items_from_rows(tok, rows, cfg[\"max_len\"], cfg[\"head_max_len\"])\n",
            "print(f\"Preprocessed {len(items)} items (skipped {skipped})\")\n",
            "torch.save(items, \"/kaggle/working/train_items.pt\")\n",
            "print(\"Saved train_items.pt\")"
        ]
    })

    # [4] Train script (single GPU, dataset pequeno)
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 3. Train (single T4)\n",
            "\n",
            "Dataset pequeno (~300 items) → single GPU é suficiente.\n",
            "RLCD objective do `laya.train`, 8 epochs, temperature calibration no fim."
        ]
    })
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "%%writefile /kaggle/working/train_single.py\n",
            "\"\"\"Single-GPU fine-tune do Laya pro dataset JARVIS (difficulty).\"\"\"\n",
            "import os, sys, time, json, random, math\n",
            "import numpy as np\n",
            "import torch\n",
            "from safetensors.torch import load_file\n",
            "from transformers import AutoTokenizer\n",
            "\n",
            "from laya.common import build_model, collate_items\n",
            "from laya.calibrate import fit_temperature_map\n",
            "from laya.train import (\n",
            "    calibration_records, encode_item, rlcd_loss,\n",
            "    save_checkpoint, sigma_at, split_calibration,\n",
            ")\n",
            "\n",
            "def main():\n",
            "    device = torch.device(\"cuda\" if torch.cuda.is_available() else \"cpu\")\n",
            "    model_dir, output_dir = sys.argv[1], sys.argv[2]\n",
            "\n",
            "    with open(os.path.join(model_dir, \"rl_agent_config.json\")) as f:\n",
            "        cfg = json.load(f)\n",
            "    cfg[\"gradient_checkpointing\"] = True\n",
            "    cfg[\"max_tokens_per_batch\"] = 2048\n",
            "    cfg[\"max_len\"] = 512\n",
            "    cfg[\"head_max_len\"] = 192\n",
            "    max_len, head_max_len = cfg[\"max_len\"], cfg[\"head_max_len\"]\n",
            "\n",
            "    tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, \"tokenizer\"))\n",
            "    model = build_model(cfg, encoder_dir=os.path.join(model_dir, \"encoder\"))\n",
            "    weights = load_file(os.path.join(model_dir, \"model.safetensors\"))\n",
            "    model.load_state_dict(weights, strict=True)\n",
            "    if hasattr(model.encoder, \"gradient_checkpointing_enable\"):\n",
            "        model.encoder.gradient_checkpointing_enable(\n",
            "            gradient_checkpointing_kwargs={\"use_reentrant\": False})\n",
            "    model.head_checkpointing = True\n",
            "    model.to(device).train()\n",
            "\n",
            "    all_items = torch.load(\"/kaggle/working/train_items.pt\", weights_only=False)\n",
            "    train_items, calib_items = split_calibration(\n",
            "        all_items, calib_max=64, calib_frac=0.15, seed=42)\n",
            "    print(f\"train={len(train_items)} calib={len(calib_items)}\")\n",
            "\n",
            "    EPOCHS, MICRO_BATCH, GRAD_ACCUM, GROUP_SIZE = 8, 8, 2, 4\n",
            "    LR_ENCODER, LR_HEAD = 2.0e-5, 8.0e-5\n",
            "    SIGMA_START, SIGMA_END = 0.4, 0.1\n",
            "\n",
            "    enc_p = [p for n, p in model.named_parameters() if \"encoder.\" in n]\n",
            "    head_p = [p for n, p in model.named_parameters() if \"encoder.\" not in n]\n",
            "    opt = torch.optim.AdamW(\n",
            "        [{\"params\": enc_p, \"lr\": LR_ENCODER}, {\"params\": head_p, \"lr\": LR_HEAD}],\n",
            "        weight_decay=0.01)\n",
            "    total = (len(train_items) // (MICRO_BATCH * GRAD_ACCUM)) * EPOCHS\n",
            "    sched = torch.optim.lr_scheduler.CosineAnnealingLR(\n",
            "        opt, T_max=max(1, total), eta_min=1e-6)\n",
            "    scaler = torch.amp.GradScaler(\"cuda\", enabled=device.type == \"cuda\")\n",
            "\n",
            "    t0 = time.time()\n",
            "    for epoch in range(EPOCHS):\n",
            "        random.seed(42 + epoch)\n",
            "        random.shuffle(train_items)\n",
            "        epoch_loss, n_batches, accum = 0.0, 0, 0\n",
            "        opt.zero_grad(set_to_none=True)\n",
            "        sigma = sigma_at(epoch, EPOCHS, SIGMA_START, SIGMA_END)\n",
            "\n",
            "        for b_idx in range(0, len(train_items), MICRO_BATCH):\n",
            "            chunk = train_items[b_idx:b_idx + MICRO_BATCH]\n",
            "            if not chunk:\n",
            "                continue\n",
            "            encoded = [encode_item(tok, it, max_len, head_max_len) for it in chunk]\n",
            "            batch = collate_items([encoded], tok.pad_token_id)\n",
            "            dtype = torch.float16 if device.type == \"cuda\" else torch.bfloat16\n",
            "            with torch.autocast(device_type=device.type, dtype=dtype):\n",
            "                logits, _ = model(\n",
            "                    batch[\"input_ids\"].to(device),\n",
            "                    batch[\"attention_mask\"].to(device),\n",
            "                    batch[\"marker_pos\"].to(device),\n",
            "                    batch[\"marker_mask\"].to(device),\n",
            "                    batch[\"qtype\"].to(device))\n",
            "            logits = logits.float()\n",
            "            loss = rlcd_loss(\n",
            "                logits, batch[\"target\"].to(device),\n",
            "                batch[\"marker_mask\"].to(device),\n",
            "                batch[\"qtype\"].to(device), sigma,\n",
            "                samples=GROUP_SIZE, w_sph=0.75, w_rps=1.0)\n",
            "            scaler.scale(loss / GRAD_ACCUM).backward()\n",
            "            accum += 1\n",
            "            if accum % GRAD_ACCUM == 0 or (b_idx + MICRO_BATCH) >= len(train_items):\n",
            "                scaler.unscale_(opt)\n",
            "                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)\n",
            "                scaler.step(opt)\n",
            "                scaler.update()\n",
            "                sched.step()\n",
            "                opt.zero_grad(set_to_none=True)\n",
            "            epoch_loss += loss.item()\n",
            "            n_batches += 1\n",
            "            if n_batches % 20 == 0:\n",
            "                print(f\"  ep{epoch+1} step{n_batches} loss={loss.item():.4f}\")\n",
            "\n",
            "        print(f\"=== Epoch {epoch+1}/{EPOCHS} avg_loss={epoch_loss/max(1,n_batches):.4f} ===\")\n",
            "\n",
            "    # Temperature calibration\n",
            "    model.eval()\n",
            "    try:\n",
            "        records = calibration_records(\n",
            "            model, tok, calib_items, device, max_len, head_max_len, batch_size=16)\n",
            "        fitted = fit_temperature_map(records)\n",
            "        temps = fitted[\"temperature\"]\n",
            "        print(\"Fitted temps:\", [round(t, 3) for t in temps])\n",
            "    except Exception as e:\n",
            "        print(\"Calib fallback:\", e)\n",
            "        temps, fitted = None, {\"temperature_by_options\": {}}\n",
            "\n",
            "    out_cfg = dict(cfg, max_len=max_len, head_max_len=head_max_len)\n",
            "    out_cfg[\"fine_tuned\"] = True\n",
            "    out_cfg[\"model_name\"] = \"laya-jarvis-difficulty\"\n",
            "    if temps is not None:\n",
            "        out_cfg[\"temperature\"] = temps\n",
            "        out_cfg.pop(\"temperature_by_options\", None)\n",
            "        out_cfg.update(fitted.get(\"temperature_by_options\", {}))\n",
            "    save_checkpoint(model, tok, out_cfg, output_dir)\n",
            "    print(f\"Saved to {output_dir} in {time.time()-t0:.1f}s\")\n",
            "\n",
            "if __name__ == \"__main__\":\n",
            "    main()"
        ]
    })

    # [5] Launch train
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "OUTPUT_DIR = \"/kaggle/working/laya_jarvis_difficulty\"\n",
            "!python /kaggle/working/train_single.py {model_dir} {OUTPUT_DIR}"
        ]
    })

    # [6] Evaluate
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 4. Evaluate\n",
            "\n",
            "Compara fine-tuned vs baseline no test split."
        ]
    })
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import time, json\n",
            "import laya\n",
            "\n",
            "# Carrega test rows (formato HF)\n",
            "test_rows_hf = hf_test\n",
            "\n",
            "agent_ft = laya.Agent(OUTPUT_DIR, device=\"cuda\" if torch.cuda.is_available() else \"cpu\")\n",
            "agent_base = laya.Agent(model_dir, device=\"cuda\" if torch.cuda.is_available() else \"cpu\")\n",
            "\n",
            "def evaluate(agent, rows):\n",
            "    correct, total = 0, 0\n",
            "    per_label = {\"simple\": [0,0], \"moderate\": [0,0], \"hard\": [0,0]}\n",
            "    latencies = []\n",
            "    for row in rows:\n",
            "        state = json.loads(row[\"state\"])\n",
            "        questions = json.loads(row[\"questions\"])\n",
            "        gold = json.loads(row[\"gold\"])\n",
            "        gold_choice = gold[0][\"choice\"]\n",
            "        t0 = time.perf_counter()\n",
            "        res = agent.predict(state, questions)\n",
            "        latencies.append((time.perf_counter() - t0) * 1000)\n",
            "        pred = res[\"answers\"][0].get(\"choice\") if isinstance(res[\"answers\"][0], dict) else res[\"answers\"][0]\n",
            "        total += 1\n",
            "        if pred == gold_choice:\n",
            "            correct += 1\n",
            "        if gold_choice in per_label:\n",
            "            per_label[gold_choice][1] += 1\n",
            "            if pred == gold_choice:\n",
            "                per_label[gold_choice][0] += 1\n",
            "    acc = correct / max(1, total)\n",
            "    lat = sum(latencies) / max(1, len(latencies))\n",
            "    return acc, per_label, lat\n",
            "\n",
            "acc_ft, per_ft, lat_ft = evaluate(agent_ft, test_rows_hf)\n",
            "acc_base, per_base, lat_base = evaluate(agent_base, test_rows_hf)\n",
            "\n",
            "print(f\"\\n{'='*50}\")\n",
            "print(f\"BASELINE (Laya base): {acc_base:.1%} avg latency {lat_base:.0f}ms\")\n",
            "for l, (c, t) in per_base.items():\n",
            "    if t: print(f\"  {l}: {c}/{t} = {c/t:.1%}\")\n",
            "print(f\"\\nFINE-TUNED: {acc_ft:.1%} avg latency {lat_ft:.0f}ms\")\n",
            "for l, (c, t) in per_ft.items():\n",
            "    if t: print(f\"  {l}: {c}/{t} = {c/t:.1%}\")\n",
            "print(f\"\\nDelta: {acc_ft - acc_base:+.1%}\")"
        ]
    })

    # [7] Push to Hub
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 5. Push to Hugging Face Hub\n",
            "\n",
            "Adiciona HF_TOKEN nos Secrets do Kaggle (Add-ons → Secrets)."
        ]
    })
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "import os\n",
            "from huggingface_hub import HfApi\n",
            "\n",
            "HF_REPO = \"SEU_USUARIO/laya-jarvis-difficulty\"  # ← ajuste\n",
            "api = HfApi()\n",
            "api.create_repo(HF_REPO, exist_ok=True, private=False)\n",
            "api.upload_folder(\n",
            "    folder_path=OUTPUT_DIR,\n",
            "    repo_id=HF_REPO,\n",
            "    commit_message=\"fine-tune Laya on JARVIS difficulty dataset\",\n",
            ")\n",
            "print(f\"Pushed to https://huggingface.co/{HF_REPO}\")"
        ]
    })

    # [8] Export report
    cells.append({
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [
            "report = {\n",
            "    \"dataset\": \"jarvis-difficulty\",\n",
            "    \"n_train\": len(train_rows),\n",
            "    \"n_test\": len(test_rows),\n",
            "    \"baseline_acc\": acc_base,\n",
            "    \"finetuned_acc\": acc_ft,\n",
            "    \"delta\": acc_ft - acc_base,\n",
            "    \"finetuned_latency_ms\": lat_ft,\n",
            "}\n",
            "with open(\"/kaggle/working/report.json\", \"w\") as f:\n",
            "    json.dump(report, f, indent=2)\n",
            "print(json.dumps(report, indent=2))"
        ]
    })

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="/tmp/laya-dataset")
    parser.add_argument("--out", default="/tmp/laya_finetune_jarvis.ipynb")
    args = parser.parse_args()

    nb = build_notebook(args.dataset)
    Path(args.out).write_text(json.dumps(nb, indent=1, ensure_ascii=False))
    print(f"Notebook saved: {args.out}")
    print(f"Cells: {len(nb['cells'])} ({sum(1 for c in nb['cells'] if c['cell_type']=='code')} code)")


if __name__ == "__main__":
    main()
