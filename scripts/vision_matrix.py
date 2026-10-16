#!/usr/bin/env python3
"""vision_matrix.py — testa cada VLM candidato UM POR UM com screenshot real.
Uso: python3 vision_matrix.py [imagem]  (default: trade2p-A-mais12s.png)
Classifica OK/RATE_LIMIT/DEAD/PAID/AUTH/ERROR + latência; JSON em
/tmp/opencode/vision_matrix.json. Verde 15/10 (4/8 OK: gemini 2.5-flash,
flash-lite, cloudflare scout NOVO, nvidia 11b lento; 90b timeout).
"""
"""vision_matrix.py — testa cada VLM candidato UM POR UM com screenshot real.
Uso: python3 vision_matrix.py [imagem]  (default: trade2p-A-mais12s.png)
Classifica OK / RATE_LIMIT / DEAD / PAID / AUTH / ERROR + mede latência."""
import base64, io, json, os, re, sys, time, urllib.request, urllib.error

ENV = {}
for line in open('/etc/litellm.env'):
    m = re.match(r'\s*export\s+([A-Za-z_][A-Za-z0-9_]*)="?(.*?)"?\s*$', line)
    if m and not line.strip().startswith('#'):
        ENV[m.group(1)] = m.group(2)

IMG = sys.argv[1] if len(sys.argv) > 1 else '/tmp/opencode/trade2p-A-mais12s.png'
Q = ("List the visible UI windows/panels and any readable text. "
     "Only describe what is clearly visible.")
RES = []

def jpg_b64(path, size=1024):
    from PIL import Image
    img = Image.open(path).convert('RGB')
    img.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=80)
    return base64.b64encode(buf.getvalue()).decode()

def oai_chat(url, headers, model, b64, mt=600, to=60):
    body = json.dumps({"model": model, "messages": [{
        "role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": Q}]}], "max_tokens": mt,
        "temperature": 0.0}).encode()
    t0 = time.time()
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=to) as r:
            d = json.loads(r.read())
            txt = (d.get('choices', [{}])[0].get('message', {}).get('content', '') or '').strip()
            dt = time.time() - t0
            return ('OK', txt[:80], dt) if txt else ('EMPTY', '', dt)
    except urllib.error.HTTPError as e:
        try: msg = json.dumps(json.loads(e.read())).lower()
        except Exception: msg = ''
        dt = time.time() - t0
        if e.code == 429 or 'rate' in msg or 'quota' in msg: return ('RATE_LIMIT', msg[:60], dt)
        if e.code == 404 or 'not found' in msg: return ('DEAD', msg[:60], dt)
        if e.code in (402, 403) or 'payment' in msg or 'credit' in msg: return ('PAID', msg[:60], dt)
        if e.code == 401: return ('AUTH', msg[:60], dt)
        return ('ERROR', f"HTTP {e.code} {msg[:60]}", dt)
    except Exception as e:
        return ('ERROR', str(e)[:80], time.time() - t0)

def rec(prov, model, st, txt, dt):
    RES.append({"provider": prov, "model": model, "status": st,
                "ms": int(dt * 1000), "txt": txt})
    print(f"{st:10} {dt:5.1f}s {prov:12} {model:48} {txt[:60]}")
    sys.stdout.flush()

B64 = jpg_b64(IMG)
NH = {"Authorization": f"Bearer {ENV.get('NVIDIA_API_KEY','')}", "Content-Type": "application/json"}
OH = {"Authorization": f"Bearer {ENV.get('OPENROUTER_API_KEY','')}", "Content-Type": "application/json",
      "HTTP-Referer": "http://localhost:5173", "X-Title": "Jarvis"}
CF = {"Authorization": f"Bearer {ENV.get('CLOUDFLARE_API_TOKEN','')}", "Content-Type": "application/json"}
CO = {"Authorization": f"Bearer {ENV.get('COHERE_API_KEY','')}", "Content-Type": "application/json"}
CFB = f"https://api.cloudflare.com/client/v4/accounts/{ENV.get('CLOUDFLARE_ACCOUNT_ID','')}/ai/v1/chat/completions"

# GOOGLE nativo
for m in ["gemini-2.5-flash", "gemini-2.5-flash-lite"]:
    body = json.dumps({"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": B64}},
        {"text": Q}]}], "generationConfig": {"maxOutputTokens": 600,
        "temperature": 0.0, "thinkingConfig": {"thinkingBudget": 0}}}).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
        data=body, headers={"x-goog-api-key": ENV.get('GEMINI_API_KEY',''),
                             "Content-Type": "application/json"}, method='POST')
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
            c = d.get('candidates', [])
            t = ''.join(p.get('text','') for p in c[0].get('content',{}).get('parts',[])) if c else ''
            rec('google', m, 'OK' if t.strip() else 'EMPTY', t.strip()[:80], time.time()-t0)
    except urllib.error.HTTPError as e:
        try: msg = json.dumps(json.loads(e.read())).lower()
        except Exception: msg = ''
        dt = time.time()-t0
        rec('google', m, 'RATE_LIMIT' if e.code==429 or 'rate' in msg else
            ('DEAD' if e.code==404 else 'ERROR'), f"HTTP {e.code} {msg[:60]}", dt)
    except Exception as e:
        rec('google', m, 'ERROR', str(e)[:80], time.time()-t0)
    time.sleep(1)

# NVIDIA NIM VLMs
for m in ["meta/llama-3.2-90b-vision-instruct", "meta/llama-3.2-11b-vision-instruct",
          "nvidia/nemotron-3.5-super-vl-120b-a12b"]:
    st, txt, dt = oai_chat("https://integrate.api.nvidia.com/v1/chat/completions", NH, m, B64)
    rec('nvidia', m, st, txt, dt)
    time.sleep(1)

# OPENROUTER :free
for m in ["google/gemma-4-31b-it:free"]:
    st, txt, dt = oai_chat("https://openrouter.ai/api/v1/chat/completions", OH, m, B64)
    rec('openrouter', m, st, txt, dt)
    time.sleep(1)

# CLOUDFLARE (llama-4-scout vision?)
for m in ["@cf/meta/llama-4-scout-17b-16e-instruct"]:
    st, txt, dt = oai_chat(CFB, CF, m, B64)
    rec('cloudflare', m, st, txt, dt)
    time.sleep(1)

# COHERE (aya-vision?)
for m in ["c4ai-aya-vision-8b"]:
    st, txt, dt = oai_chat("https://api.cohere.ai/compatibility/v1/chat/completions", CO, m, B64)
    rec('cohere', m, st, txt, dt)

json.dump(RES, open('/tmp/opencode/vision_matrix.json', 'w'), indent=1)
print(f"\n=== {sum(1 for r in RES if r['status']=='OK')}/{len(RES)} OK ===")
