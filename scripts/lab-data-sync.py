#!/usr/bin/env python3
"""lab-data-sync — gera os marcos do /lab a partir de JSONs MEDIDOS.

Lê lab-facts.json versionado (via git archive de origin/main, sem tocar no
working tree) + JSONs das frentes em ~/work/hybrid e escreve
tools/lab-timeline/mach-stages.generated.{json,js}. Nenhum número é digitado
à mão na view: se o JSON da frente não existe, o marco não aparece.
"""
from __future__ import annotations
import json, re, subprocess, tempfile
from pathlib import Path

H = Path('/home/nixos')
B = H / 'work/hybrid'
T = H / 'projects/nixos-ai/tools/lab-timeline'
FRENTES = {
    'f154-capacity-s42.json': ('f154', 'F154 · capacidade d1408'),
    'f156-elastic-s42.json': ('f156', 'F156 · elastic depth'),
    'f159-learned.json': ('f159-learned', 'F159 · learned seq1024'),
    'f159-rope.json': ('f159-rope', 'F159 · RoPE seq1024'),
    'f159-alibi.json': ('f159-alibi', 'F159 · ALiBi seq1024'),
}


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def add(out, fid, label, d, val, acc, steps, vram, secs, corpus, note):
    if val is None:
        return
    out.append({'id': fid, 'date': '28/11', 'label': label, 'd': d, 'params': None,
                'val': val, 'acc': acc, 'steps': steps, 'corpus': corpus,
                'note': note, 'vram': vram, 'seconds': secs})


JS_EXTRACT = r"""
const fs=require('fs');
const h=fs.readFileSync(process.argv[1],'utf8');
const m=h.match(/const MACH_STAGES=(\[[\s\S]*?\n\]);/);
if(!m){process.exit(2);}
process.stdout.write(JSON.stringify(eval(m[1])));
"""


def base_stages() -> list:
    """Lê os marcos narrativos do index.html avaliando o literal com Node."""
    try:
        r = subprocess.run(['node', '-e', JS_EXTRACT, str(T / 'index.html')],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception:
        pass
    return []


def main() -> int:
    stages = base_stages()
    with tempfile.TemporaryDirectory() as td:
        repo = H / 'projects/ai-mesh'
        subprocess.run(['git', '-C', str(repo), 'fetch', 'origin', 'main', '-q'], check=True)
        with open(Path(td) / 'facts.tar', 'wb') as fh:
            subprocess.run(['git', '-C', str(repo), 'archive', 'origin/main',
                            'docs/lab-facts.json'], stdout=fh, check=True)
        subprocess.run(['tar', '-x', '-f', str(Path(td) / 'facts.tar'), '-C', td], check=True)
        facts = load(Path(td) / 'docs/lab-facts.json') or {}
    for g in facts.get('gates', []):
        if g.get('status') in ('passado', 'rejeitado', 'reprovado') and isinstance(g.get('value'), (int, float)):
            stages.append({'id': str(g['id']).lower().replace(' ', '-'), 'date': '28/11',
                           'label': str(g['id']), 'd': None, 'params': None,
                           'val': g['value'], 'acc': None, 'steps': None,
                           'corpus': 'lab-facts.json',
                           'note': str(g.get('threshold') or '')[:110],
                           'vram': None, 'seconds': None})
    for fn, (fid, label) in FRENTES.items():
        r = load(B / fn)
        if not r:
            continue
        add(stages, fid, label, r.get('d'), r.get('val_loss'), r.get('acc'),
            r.get('steps'), r.get('peak_vram_bytes'), r.get('seconds'),
            'SimpleStories ownremap 210M', 'numero lido do JSON da frente')
    for m in ('learned', 'rope', 'alibi'):
        r = load(B / f'f160-{m}.json')
        if r:
            add(stages, f'f160-{m}', f'F160 · {m} seq4096', r.get('d'),
                r.get('val_loss'), r.get('acc'), r.get('steps'),
                r.get('vram_bytes'), r.get('seconds'),
                'SimpleStories ownremap 210M', 'seq4096 — gate F98')
    for tag in ('f161-itq', 'f162-itq'):
        r = load(B / f'{tag}.json')
        if not r:
            continue
        for x in r.get('results', []):
            add(stages, f"{tag}-d{x['d']}", f"{'F161' if tag.startswith('f161') else 'F162'} · ITQ d{x['d']}",
                x['d'], x['itq']['val_loss'], x['itq']['acc'], r.get('steps'), None,
                x['itq']['seconds'], 'TinyStories bytes',
                'ortho_err=' + str(x['itq'].get('ortho_err')))
    seen, uniq = set(), []
    for s in stages:
        if s['id'] not in seen:
            seen.add(s['id'])
            uniq.append(s)
    T.mkdir(parents=True, exist_ok=True)
    (T / 'mach-stages.generated.json').write_text(
        json.dumps(uniq, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    def lit(s):
        q = lambda v: str(v).replace("'", '').replace('\n', ' ')[:110]
        n = lambda v: 'null' if v is None else v
        return ("{id:'%s',date:'%s',label:'%s',d:%s,params:%s,val:%s,acc:%s,"
                "steps:%s,corpus:'%s',note:'%s'}") % (
                    q(s['id']), q(s['date']), q(s['label']), n(s['d']), n(s['params']),
                    n(s['val']), n(s['acc']), n(s['steps']), q(s['corpus']), q(s['note']))
    (T / 'mach-stages.generated.js').write_text(
        'const MACH_STAGES=[\n' + ',\n'.join(' ' + lit(s) for s in uniq) + '\n];\n',
        encoding='utf-8')
    novos = [s['id'] for s in uniq if s['id'].startswith(
        ('f154', 'f156', 'f159', 'f160', 'f161', 'f143', 'f144'))]
    print(json.dumps({'stages': len(uniq), 'novos': novos[-20:]}, ensure_ascii=False))
    return 0 if uniq else 2


if __name__ == '__main__':
    raise SystemExit(main())
