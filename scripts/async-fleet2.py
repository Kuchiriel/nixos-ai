#!/usr/bin/env python3
"""async-fleet v2 — poller nao bloqueante para GPU local + Kaggle."""
from __future__ import annotations
import json, subprocess, time
from pathlib import Path

HERE = Path('/home/nixos')
EVENTS = HERE / 'work/hybrid/async-events.jsonl'
PHONE = 'u0_a438@100.104.175.123'
AW = '/data/data/com.termux/files/home/bin/auto-wake'
PRIN = 'improver-termux-fast@termux:ses_e52816aa7ffe4zi1iV7cJ8mvtc'
JOBS = [
    {'id': 'F154-H1', 'kind': 'file',
     'path': str(HERE / 'work/hybrid/f154-capacity-s42.json'),
     'task': 'improver-termux-fast: termux/F154-H1-capacidade',
     'reason': 'F154 concluido: ler val_loss/acc/VRAM/tempo do JSON e aplicar gate H1 (val<=1,6782 e acc>=0,556) contra controle 167M 1,6962/0,5685; comparacao com batch2 diferente -> repetir controle se passar.'},
    {'id': 'KAGGLE-BETA-ANCHOR', 'kind': 'kaggle',
     'slug': 'kuchiriel/kaggle-beta-anchor',
     'task': 'improver-termux-fast: termux/F143-alien-calibracao',
     'reason': 'Kernel Kaggle kuchiriel/kaggle-beta-anchor concluido: puxar beta-anchor-kaggle.json, medir val/acc/ECE em 3 tamanhos e aplicar gate NOVO pre-registrado (val+ECE, nao renegociar o gate reprovado).'},
]


def phone(*args: str) -> tuple[int, str]:
    cmd = ['ssh', '-o', 'ConnectTimeout=6', '-o', 'BatchMode=yes',
           '-p', '8022', PHONE, '--'] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout or r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, 'timeout'


def kaggle(account: str, *args: str) -> str:
    cmd = [str(HERE / 'bin/kaggle-conta'), account] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 'timeout'


def main() -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if EVENTS.exists():
        for line in EVENTS.read_text(errors='ignore').splitlines():
            try:
                done.add(json.loads(line).get('id'))
            except Exception:
                pass
    with EVENTS.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'event':'start_v2','ts':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'jobs':len(JOBS)}) + '\n')
    while True:
        for job in JOBS:
            if job['id'] in done:
                continue
            ok = False
            if job['kind'] == 'file':
                ok = Path(job['path']).exists()
            elif job['kind'] == 'kaggle':
                status = kaggle('kuchiriel', 'kernels', 'status', job['slug'])
                ok = 'COMPLETE' in status.upper()
                if 'ERROR' in status.upper():
                    ok = True  # tambem fecha para inspecionar o erro
            if not ok:
                continue
            rec = {'event':'job_done','id':job['id'],'ts':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
            if job['kind'] == 'kaggle':
                rec['pull'] = kaggle('kuchiriel', 'kernels', 'pull', job['slug'], '-p', str(HERE / 'work/hybrid/kaggle-beta-anchor-out'))[:200]
            with EVENTS.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            rc, out = phone(AW, 'complete', json.dumps(job['task']),
                            '--principal', json.dumps(PRIN), '--reason', json.dumps(job['reason']))
            with EVENTS.open('a', encoding='utf-8') as f:
                f.write(json.dumps({'event':'complete','id':job['id'],'rc':rc,'out':out[:160]}, ensure_ascii=False) + '\n')
            done.add(job['id'])
        time.sleep(60)


if __name__ == '__main__':
    main()
