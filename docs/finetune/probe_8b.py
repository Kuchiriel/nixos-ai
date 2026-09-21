"""Fit probe: QLoRA-8B Bonsai-unpacked (r8, paged-8bit, ckpt, seq 1024).
5 steps dummy. GOAL: peak VRAM + survival verdict (evidence, not hope).
"""
import time
import torch
from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig

BASE = "/home/nixos/.cache/bonsai-unpacked"
torch.cuda.reset_peak_memory_stats()
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=torch.bfloat16, llm_int8_enable_fp32_cpu_offload=True)
tok = AutoTokenizer.from_pretrained(BASE)
model = AutoModelForCausalLM.from_pretrained(BASE, quantization_config=bnb,
                                             device_map="auto", max_memory={0: "5200MB", "cpu": "25GB"},
                                             torch_dtype=torch.bfloat16)
# sem upcast fp32 (OOM em 6GB): ckpt manual + norms em bf16 (probe de fit, não qualidade)
model.gradient_checkpointing_enable()
model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
                                         task_type="CAUSAL_LM",
                                         target_modules=["q_proj", "k_proj", "v_proj",
                                                         "o_proj", "gate_proj",
                                                         "up_proj", "down_proj"]))
n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f"TRAINABLE: {n_train/1e6:.1f}M")
data = Dataset.from_list([{"text": "Instruction: write json.\nOutput: {\"a\": 1}\n"}] * 32)
args = SFTConfig(output_dir="/tmp/ft-8b", per_device_train_batch_size=1,
                 gradient_accumulation_steps=1, max_steps=5, max_length=512,
                 learning_rate=2e-4, optim="paged_adamw_8bit",
                 fp16=False, bf16=True, logging_steps=1, save_steps=100,
                 report_to="none", gradient_checkpointing=True,
                 dataset_text_field="text", loss_type="nll")
t0 = time.monotonic()
tr = SFTTrainer(model=model, train_dataset=data, args=args)
tr.train()
dt = time.monotonic() - t0
peak = torch.cuda.max_memory_allocated() / 1e9
print(f"STEPS=5 time={dt:.1f}s peak={peak:.2f}GB")
print("FIT-8B-OK")
