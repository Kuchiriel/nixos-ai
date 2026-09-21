"""Stack validation: QLoRA Qwen3-0.6B (same family as Bonsai base).
20 steps dummy data, seq 1024. Measures: peak VRAM, tok/s, stability.
Proves bnb+peft+trl+CUDA work on this NixOS box BEFORE the 16GB pull.
"""
import time
import torch
from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig

MODEL = "Qwen/Qwen3-0.6B"
torch.cuda.reset_peak_memory_stats()
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=torch.float16)
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb,
                                             device_map="auto")
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
model.gradient_checkpointing_enable()
model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
                                         task_type="CAUSAL_LM"))
data = Dataset.from_list([{"text": "Instruction: write json.\nOutput: {\"a\": 1}\n"}] * 64)
args = SFTConfig(output_dir="/tmp/ft-probe", per_device_train_batch_size=1,
                 gradient_accumulation_steps=1, max_steps=20, max_length=1024,
                 learning_rate=2e-4, optim="adamw_torch", fp16=False, bf16=True,
                 logging_steps=5, save_steps=100, report_to="none",
                 gradient_checkpointing=True, dataset_text_field="text")
t0 = time.monotonic()
tr = SFTTrainer(model=model, train_dataset=data, args=args)
tr.train()
dt = time.monotonic() - t0
peak = torch.cuda.max_memory_allocated() / 1e9
print(f"STEPS=20 time={dt:.1f}s peak={peak:.2f}GB tok/s~{(20*1024*1)/dt:.0f}")
print("STACK-OK")
