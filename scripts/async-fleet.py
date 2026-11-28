#!/usr/bin/env python3
"""async-fleet — orquestrador nao bloqueante (host local).

Roda em background, poll curto, e quando um job termina:
  - escreve resultado em ~/work/hybrid/async-events.jsonl (append-only)
  - chama ~/bin/auto-wake no CELULAR por SSH (PC->celular OK)
  - publica no bus pelo celular (token nunca no host)
Nao toca identidade/plugin/comms (outros agentes estao la).
"""
from __future__ import annotations
import json, os, subprocess, time
from pathlib import Path

HERE = Path('/home/nixos')
EVENTS = HERE / 'work/hybrid/async-events.jsonl'
PHONE = os.environ.get('TERMUX_PHONE_SSH','u0_a438@100.104.175.123')
PHONE_PORT = 8022
AW = '/data/data/com.termux/files/home/bin/auto-wake'
BUS = '/data/data/com.termux/files/home/bin/bus-post'
PRIN = 'improver-termux-fast@termux:ses_e52816aa7ffe4zi1iV7cJ8mvtc'
JOBS = [
    {
        'id': 'F154-H1',
        'json': str(HERE / 'work/hybrid/f154-capacity-s42.json'),
        'task': 'improver-termux-fast: termux/F154-H1-capacidade',
        'reason': ('F154 concluido: ler val_loss/acc/VRAM/tempo do JSON e aplicar gate H1 '
                   '(val<=1,6782 e acc>=0,556) contra controle 167M 1,6962/0,5685. '
                   'Comparacao com batch2 diferente do controle -> repetir controle se passar.'),
    },
]


def phone(*args: str) -> tuple[int, str]:
    cmd = ['ssh', '-o', 'ConnectTimeout=6', '-o', 'BatchMode=yes',
           '-p', str(PHONE_PORT), PHONE, '--'] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout or r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, 'timeout'


def main() -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if EVENTS.exists():
        for line in EVENTS.read_text(errors='ignore').splitlines():
            try:
                d = json.loads(line); done.add(d.get('id'))
            except Exception:
                pass
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with EVENTS.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'event':'start','ts':started,'jobs':len(JOBS)}) + '\n')
    while True:
        for job in JOBS:
            if job['id'] in done:
                continue
            jp = Path(job['json'])
            if not jp.exists():
                continue
            try:
                data = json.loads(jp.read_text())
            except Exception:
                continue
            rec = {'event':'job_done','id':job['id'],'ts':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                   'val_loss':data.get('val_loss'),'acc':data.get('acc'),
                   'seconds':data.get('seconds'),'peak_vram_bytes':data.get('peak_vram_bytes')}
            with EVENTS.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            rc, out = phone(AW, 'complete', json.dumps(job['task']),
                            '--principal', json.dumps(PRIN), '--reason', json.dumps(job['reason']))
            rec['complete_rc'] = rc; rec['complete_out'] = out[:150]
            with EVENTS.open('a', encoding='utf-8') as f:
                f.write(json.dumps({'event':'complete','id':job['id'],'rc':rc,'out':out[:150]}) + '\n')
            done.add(job['id'])
        time.sleep(60)

if __name__ == '__main__':
    main()
