#!/usr/bin/env python3
"""provider_matrix.py — audit de TODOS os LLM providers do dono (keys de
/etc/litellm.env) contra os endpoints reais; classifica OK / RATE_LIMIT /
DEAD / PAID / AUTH / ERROR. Fonte do catalogo enabled_providers do home.nix.
  use:  python3 provider_matrix.py           (34 testes, ~3min; JSON em
       /tmp/opencode/provider_matrix.json; gemini thinking precisa
       max_tokens>=512 — igual no opencode, probe curto = vazio)
  origem: 15/10 crise "modelos sumiram" (freellmapi enabled_providers
       sobrepondo a global); verde em 34/34 classificados.
"""
"""provider_matrix.py — testa TODOS providers×modelos do catalogo home.nix.
Classifica: OK / RATE_LIMIT / DEAD / PAID / ERROR. Salva JSON p/ gerar nix."""
import json, os, re, sys, time, urllib.request, urllib.error

ENV = {}
for line in open('/etc/litellm.env'):
    m = re.match(r'\s*export\s+([A-Za-z_][A-Za-z0-9_]*)="?(.*?)"?\s*$', line)
    if m and not line.strip().startswith('#'):
        ENV[m.group(1)] = m.group(2)

def key(n):
    return ENV.get(n, '')

PROMPT = "Reply with exactly: OK"

def chat(url, headers, model, mt=512, to=45):
    body = json.dumps({"model": model, "messages": [
        {"role": "user", "content": PROMPT}], "max_tokens": mt}).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=to) as r:
            d = json.loads(r.read())
            c = ''
            if 'choices' in d and d['choices']:
                c = (d['choices'][0].get('message') or {}).get('content', '') or ''
                # gemini thinking: pode vir razoing_content; resposta vazia com finish=thought
            return ('OK' if c.strip() else 'EMPTY'), c.strip()[:60]
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read())
        except Exception:
            d = {}
        msg = json.dumps(d)[:220]
        code = e.code
        low = msg.lower()
        if code == 429 or 'rate' in low or 'quota' in low or 'tpd' in low or 'rpm' in low or 'too many' in low:
            return 'RATE_LIMIT', msg
        if code == 404 or 'not found' in low or 'does not exist' in low or 'not_in_catalog' in low or 'no endpoints' in low or 'no allowed providers' in low:
            return 'DEAD', msg
        if code in (402, 403) or 'payment' in low or 'credit' in low or 'insufficient' in low or 'forbidden' in low or 'plan' in low:
            return 'PAID', msg
        if 'api key' in low or code == 401:
            return 'AUTH', msg
        return 'ERROR', msg
    except Exception as e:
        return 'ERROR', str(e)[:220]

def gkey(s):
    return {'OK': 0, 'RATE_LIMIT': 1, 'EMPTY': 2, 'ERROR': 3, 'PAID': 4, 'DEAD': 5, 'AUTH': 6}.get(s, 9)

RESULTS = []
def record(prov, model, st, msg):
    RESULTS.append({"provider": prov, "model": model, "status": st, "msg": msg})
    print(f"{st:11} {prov:12} {model:55} {msg[:70]}")
    sys.stdout.flush()

OH = {"Authorization": f"Bearer {key('OPENROUTER_API_KEY')}", "Content-Type": "application/json",
      "HTTP-Referer": "http://localhost:5173", "X-Title": "Jarvis"}
NH = {"Authorization": f"Bearer {key('NVIDIA_API_KEY')}", "Content-Type": "application/json"}
GH = {"x-goog-api-key": key('GEMINI_API_KEY') or key('GOOGLE_API_KEY'), "Content-Type": "application/json"}
GQH = {"Authorization": f"Bearer {key('GROQ_API_KEY')}", "Content-Type": "application/json"}
CH = {"Authorization": f"Bearer {key('CEREBRAS_API_KEY')}", "Content-Type": "application/json"}
CFH = {"Authorization": f"Bearer {key('CLOUDFLARE_API_TOKEN')}", "Content-Type": "application/json"}
SBH = {"Authorization": f"Bearer {key('SAMBANOVA_API_KEY')}", "Content-Type": "application/json"}
COH = {"Authorization": f"Bearer {key('COHERE_API_KEY')}", "Content-Type": "application/json"}
HFH = {"Authorization": f"Bearer {key('HF_TOKEN')}", "Content-Type": "application/json"}
BTH = {"Authorization": f"Bearer {key('BASETEN_API_KEY')}", "Content-Type": "application/json"}

def google_native(model):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({"contents": [{"parts": [{"text": PROMPT}]}],
                       "generationConfig": {"maxOutputTokens": 512}}).encode()
    req = urllib.request.Request(url, data=body, headers=GH, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read())
            cands = d.get('candidates', [])
            txt = ''
            if cands:
                txt = ''.join(p.get('text', '') for p in cands[0].get('content', {}).get('parts', []))
            if txt.strip():
                return 'OK', txt.strip()[:60]
            fin = cands[0].get('finishReason', '?') if cands else '?'
            return ('EMPTY' if fin == 'MAX_TOKENS' else 'ERROR'), f"finish={fin} {json.dumps(d)[:120]}"
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read())
        except Exception:
            d = {}
        msg = json.dumps(d)[:220]; low = msg.lower(); code = e.code
        if code == 429 or 'rate' in low or 'quota' in low:
            return 'RATE_LIMIT', msg
        if code == 404 or 'not found' in low:
            return 'DEAD', msg
        if 'api key' in low or code == 401 or code == 400 and 'api_key' in low:
            return 'AUTH', msg
        return 'ERROR', msg
    except Exception as e:
        return 'ERROR', str(e)[:220]

# ============ GOOGLE (native) ============
for m in ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash", "gemma-4-31b-it"]:
    st, msg = google_native(m)
    record('google', m, st, msg)
    time.sleep(1)

# ============ OPENROUTER ============
for m in ["nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3-super-120b-a12b:free",
          "nvidia/nemotron-3.5-lightning:free", "google/gemma-4-31b-it:free",
          "thinkingmachines/inkling:free"]:
    st, msg = chat("https://openrouter.ai/api/v1/chat/completions", OH, m)
    record('openrouter', m, st, msg)
    time.sleep(1)

# ============ GROQ ============
for m in ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
    st, msg = chat("https://api.groq.com/openai/v1/chat/completions", GQH, m)
    record('groq', m, st, msg)
    time.sleep(1)

# ============ NVIDIA NIM ============
for m in ["deepseek-ai/deepseek-v4.1-flash", "z-ai/glm-5.3-flash",
          "nvidia/nemotron-3-super-120b-a12b", "google/gemma-4-31b-it"]:
    st, msg = chat("https://integrate.api.nvidia.com/v1/chat/completions", NH, m)
    record('nvidia', m, st, msg)
    time.sleep(1)

# ============ CEREBRAS ============
for m in ["qwen-3.8-27b", "gpt-oss-120b"]:
    st, msg = chat("https://api.cerebras.ai/v1/chat/completions", CH, m)
    record('cerebras', m, st, msg)
    time.sleep(1)

# ============ CLOUDFLARE ============
cf_base = f"https://api.cloudflare.com/client/v4/accounts/{key('CLOUDFLARE_ACCOUNT_ID')}/ai/v1/chat/completions"
for m in ["@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/openai/gpt-oss-120b",
          "@cf/google/gemma-4-26b-a4b-it", "@cf/qwen/qwen3.8-27b",
          "@cf/deepseek-ai/deepseek-v4-flash-0731", "@cf/mistralai/mistral-small-3.1-24b-instruct"]:
    st, msg = chat(cf_base, CFH, m)
    record('cloudflare', m, st, msg)
    time.sleep(1)

# ============ SAMBANOVA ============
for m in ["Meta-Llama-3.3-70B-Instruct", "gpt-oss-120b", "gemma-4-31B-it", "DeepSeek-V3.2"]:
    st, msg = chat("https://api.sambanova.ai/v1/chat/completions", SBH, m)
    record('sambanova', m, st, msg)
    time.sleep(1)

# ============ COHERE ============
for m in ["command-r7b-12-2024", "command-r-plus-08-2024", "command-a-03-2025",
          "command-a-reasoning-08-2025", "north-mini-code-1-0"]:
    st, msg = chat("https://api.cohere.ai/compatibility/v1/chat/completions", COH, m)
    record('cohere', m, st, msg)
    time.sleep(1)

# ============ HUGGINGFACE ============
st, msg = chat("https://router.huggingface.co/v1/chat/completions", HFH,
               "Qwen/Qwen3-235B-A22B-Instruct-2507")
record('huggingface', "Qwen/Qwen3-235B-A22B-Instruct-2507", st, msg)

# ============ BASETEN (key existe) ============
st, msg = chat("https://inference.baseten.co/v1/chat/completions", BTH, "openai/gpt-oss-120b")
record('baseten', "openai/gpt-oss-120b", st, msg)

json.dump(RESULTS, open('/tmp/opencode/provider_matrix.json', 'w'), indent=1)
ok = sum(1 for r in RESULTS if r['status'] in ('OK', 'RATE_LIMIT', 'EMPTY'))
print(f"\n=== RESUMO: {ok}/{len(RESULTS)} usaveis (OK+RATE_LIMIT+EMPTY) ===")
for st in ('OK', 'RATE_LIMIT', 'EMPTY', 'ERROR', 'PAID', 'DEAD', 'AUTH'):
    n = sum(1 for r in RESULTS if r['status'] == st)
    if n: print(f"  {st}: {n}")
