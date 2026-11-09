#!/usr/bin/env python3
"""RECONSTRUIDO do transcript (09/11, coord-naming) — kernel Kaggle do dataset
`kuchiriel/scicom-antihalluc-pt` (os 4 parquets do trigger bench).

POR QUE ESTE ARQUIVO: o script original vivia em /tmp e foi com a limpeza
(o pipeline do VAC nao esta no repo). Recuperado dos transcripts da sessao
(opencode.db) e trazido para o repo para nao se perder de novo.

O QUE ELE DIZ (e resolve a divisao dos fixtures): os 4 parquets
(silence/nonspeech/music/reduplication, colunas id + audio.bytes) NAO sao
para "regenerados": eles sao o RECORTE PROCESSADO de um dataset PRIVADO no
Kaggle/HF. O caminho curto e' re-baixar esse dataset (o sweep cuida do
fetch) e apontar o bench para ele; este kernel e' a documentacao de como o
recorte foi feito (e como re-faze-lo, se um dia for necessario).

Ele roda DENTRO do Kaggle (usa /kaggle/input), nao localmente.
"""

import json, os, subprocess, sys

def log(m):
    print(m, flush=True)

# ── 1. setup ────────────────────────────────────────────────────────────
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                "transformers", "peft", "bitsandbytes", "accelerate",
                "datasets"], check=True)
import torch
from transformers import (WhisperForConditionalGeneration, WhisperProcessor,
                          TrainingArguments, Trainer)

assert torch.cuda.is_available()
log(f"GPU: {torch.cuda.get_device_name(0)}")
BASE = "openai/whisper-large-v3-turbo"
DATA = "/kaggle/input/scicom-antihalluc-pt"   # confere o mount na 1ª exec

# ── 2. dataset HB v2 (sint-positivos + genuine-synth + gatilhos) ────────
# arms: lexicon-synth-pt (395, frase-alvo = contrapeso) · genuine-synth-pt
# (124 kokoro, transcribe-alvo = protege fala real) · silence/nonspeech/
# music/reduplication (gatilhos, alvo VAZIO = 'nada aqui'). Gatilhos
# AMOSTRADOS p/ balancear (music.parquet tem 344MB sozinho).
from datasets import load_dataset
import pandas as pd, glob
FIX = None
for cand in ("/kaggle/input/scicom-antihalluc-pt",
             "/kaggle/input/datasets/kuchiriel/scicom-antihalluc-pt"):
    if os.path.exists(cand):
        FIX = cand; break
assert FIX, "dataset não montado"
arm_frames = []
for fname, arm, target, cap in [
        ("lexicon-synth-pt.parquet", "sint_pos", "phrase", None),
        ("genuine-synth-pt.parquet", "genuine", "transcribe", None),
        ("silence.parquet", "trigger", "empty", 500),
        ("nonspeech.parquet", "trigger", "empty", 500),
        ("music.parquet", "trigger", "empty", 400),
        ("reduplication.parquet", "trigger", "empty", 400)]:
    df = pd.read_parquet(f"{FIX}/{fname}")
    if cap and len(df) > cap:
        df = df.sample(cap, random_state=42)
    df = df.assign(arm=arm, target=target)
    arm_frames.append(df)
    log(f"{arm}: {len(df)} clips de {fname}")
df = pd.concat(arm_frames, ignore_index=True)
log(f"MIX: {len(df)} clips | arms: {df['arm'].value_counts().to_dict()}")
# (paper §8: alvo do gatilho é o transcript VAZIO sob o language token
#  PT — ensina 'nada aqui'; sint_pos ensina a frase quando REAL)

# ── 3. modelo + LoRA ────────────────────────────────────────────────────
proc = WhisperProcessor.from_pretrained(BASE)
model = WhisperForConditionalGeneration.from_pretrained(
    BASE, torch_dtype=torch.float16, device_map="cuda:0")
from peft import LoraConfig, get_peft_model
lcfg = LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
    target_modules=["q_proj", "v_proj"],   # decoder self+cross attn
    task_type="SEQ_2_SEQ_LM")
model = get_peft_model(model, lcfg)
model.print_trainable_parameters()

# ── 4. collate: audio → mel; alvo por arm ──────────────────────────────
def make_label(row):
    if row["target"] == "phrase":
        return row.get("reference_text") or row.get("text") or row.get("gold") or ""
    return ""    # trigger = vazio; genuine = o próprio texto do clip

def row_text(row):
    for c in ("reference_text", "text", "gold", "transcript"):
        if isinstance(row.get(c), str) and row[c].strip():
            return row[c].strip()
    return ""

class AntiHallucDS(torch.utils.data.Dataset):
    def __init__(self, df):
        self.rows = df.to_dict("records")
    def __len__(self):
        return len(self.rows)
    def __getitem__(self, i):
        r = self.rows[i]
        inp = proc(r["audio"]["bytes"], sampling_rate=16000,
                   return_tensors="pt")
        # genuine usa o texto real; trigger vazio; sint = frase
        lab_txt = row_text(r) if r["target"] == "transcribe" else make_label(r)
        lab = proc.tokenizer(lab_txt).input_ids
        return {"input_features": inp.input_features[0],
                "labels": torch.tensor(lab[0])}

def collate(batch):
    return {
        "input_features": torch.stack([b["input_features"] for b in batch]),
        "labels": torch.nn.utils.rnn.pad_sequence(
            [b["labels"] for b in batch], batch_first=True,
            padding_value=-100),
    }

# ── 5. treino (config do paper, fp16 p/ T4) ────────────────────────────
args = TrainingArguments(
    output_dir="/tmp/out", num_train_epochs=3,
    per_device_train_batch_size=8, gradient_accumulation_steps=2,
    learning_rate=1e-4, lr_scheduler_type="linear", warmup_steps=50,
    max_grad_norm=1.0, logging_steps=10, save_strategy="no",
    report_to="none", fp16=True, seed=42, remove_unused_columns=False,
    gradient_checkpointing=True,
    gradient_checkpointing_kwargs={"use_reentrant": False},
    dataloader_num_workers=2)
trainer = Trainer(model=model, args=args,
                  train_dataset=AntiHallucDS(df), data_collator=collate)
trainer.train()

# ── 6. eval: HR nos gatilhos + recovery nos sintéticos ──────────────────
# (benchmark de gatilhos do Scicom + PT sint; medir % de clips com
#  emissão de palavras — alvo: <10% nos gatilhos, >80% recovery)

# ── 7. salvar + caminho de conversão GGUF (a definir c/ dono) ───────────
model.save_pretrained("/kaggle/working/adapter", safe_serialization=True)
log("RASCUNHO INCOMPLETO BY DESIGN: eval §6 e conversão §7 dependem de "
    "decisão do dono (genuine-PT ausente; launch autorizado?)")
