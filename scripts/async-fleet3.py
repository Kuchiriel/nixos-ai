#!/usr/bin/env python3
"""async-fleet v3 — poller nao bloqueante para GPU local + Kaggle.

Correcao v3 (28/11 11:2xZ):
  - `complete` recebe strings cruas (json.dumps adicionava aspas literais);
  - se a tarefa nao esta claimed, usar `archive` e/ou publicar no bus —
    nunca perder o numero medido por causa de rc=3;
  - `kernels output` puxa o JSON de resultado (o `pull` so traz o codigo).
"""
from __future__ import annotations
import json, subprocess, time
from pathlib import Path

HERE = Path('/home/nixos')
EVENTS = HERE / 'work/hybrid/async-events.jsonl'
PHONE = 'u0_a438@100.104.175.123'  # PC->celular no tailnet funciona (assimetria: celular->PC caiu)
AW = '/data/data/com.termux/files/home/bin/auto-wake'
BUS = '/data/data/com.termux/files/home/bin/bus-post'
PRIN = 'improver-termux-fast@termux:ses_e52816aa7ffe4zi1iV7cJ8mvtc'
JOBS = [
    {
        'id': 'F160-posicao4096',
        'kind': 'files3',
        'paths': [str(HERE / f'work/hybrid/f160-{m}.json')
                  for m in ('learned', 'rope', 'alibi')],
        'blocked': str(HERE / 'work/hybrid/f160-blocked.json'),
        'task': 'improver-termux-fast: termux/F160-posicao-4096',
        'reason': 'F160: aguardando 3 bracos em seq4096',
    },
    {
        'id': 'F144-robustez',
        'kind': 'kaggle',
        'slug': 'kuchiriel/f144-robustez',
        'task': 'improver-termux-fast: termux/F144-robustez-calibracao',
        'reason': ('F144 CONCLUIDO: ler f144-robustez.json (seed43, sem scheduled sampling, '
                   '3 tamanhos pareados) e aplicar gate PRE-REGISTRADO em '
                   'docs/f144-robustez-pre-registro-2026-11-28.md. Nao renegociar.'),
    },
    {
        'id': 'F143-calibracao-v2',
        'kind': 'kaggle',
        'slug': 'kuchiriel/f143-calibracao-v2',
        'task': 'improver-termux-fast: termux/F143-calibracao-temperatura',
        'reason': ('F143 CONCLUIDO: ler f143-calibracao.json (corpus SimpleStories remap top-10000, '
                   '3 tamanhos pareados, 9600 passos) e aplicar gate PRE-REGISTRADO em '
                   'docs/alien-fronteira-resultado-2026-11-28.md: ECE<=base-0,01 e '
                   'val_loss<=base+0,02 e acc>=base-0,01 em todos; temperatura so no val. '
                   'Nao renegociar gate do beta-anchor reprovado. Arquivar/enfileirar F144.'),
    },
    {
        'id': 'F156-elastic',
        'kind': 'file',
        'path': str(HERE / 'work/hybrid/f156-elastic-s42.json'),
        'task': 'improver-termux-fast: termux/F156-elastic-gate',
        'reason': ('F156 ELASTIC CONCLUIDO: ler val_loss/acc/VRAM/tempo do JSON e aplicar gate '
                   'pre-registrado em docs/f156-elastic-gate-pre-registro-2026-11-28.md: '
                   'val<=1,6782 (controle F129 1,6982) e acc>=0,5560; custo >25% sem ganho '
                   'primario = nao util. Sem renegociar gate; arquivar e enfileirar F157/F159.'),
    },
    {
        'id': 'F154-H1',
        'kind': 'file',
        'path': str(HERE / 'work/hybrid/f154-capacity-s42.json'),
        'task': 'improver-termux-fast: termux/F154-H1-capacidade',
        'reason': ('F154 CONCLUIDO: val_loss 1,7044 / acc 0,5647 / perplexity 5,498 / '
                   'VRAM 4,555 GB / 7276,1 s / d1408 / 19.660.800 tokens. Gate H1 '
                   '(val<=1,6782 vs controle F129 1,6982) NAO PASSOU: 1,7044 e piora '
                   '0,0062 nat. Sem renegociacao; H1 completo (1B tokens unicos) '
                   'segue pendente como tarefa separada.'),
    },
    {
        'id': 'KAGGLE-BETA-ANCHOR',
        'kind': 'kaggle',
        'slug': 'kuchiriel/kaggle-beta-anchor',
        'task': 'improver-termux-fast: termux/F143-alien-calibracao',
        'reason': ('KAGGLE CONCLUIDO (3 tamanhos): val(d1) piora +0,0729/+0,0714/+0,0726 e '
                   'val(d4) +0,1642/+0,1641/+0,1628; ECE 0,0062->0,0042 etc; acc=0 em '
                   'todos (corpus deterministico). Gate original REPROVADO de novo. '
                   'Nova hipotese F143 pre-registrada em '
                   'docs/alien-fronteira-resultado-2026-11-28.md antes de qualquer treino.'),
    },
]


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, 'timeout'


def phone(*args: str) -> tuple[int, str]:
    # SSH remoto junta os args numa linha de shell: sem shlex.quote,
    # parenteses/- em reason viram syntax error (medido 11:24Z, rc=2).
    import shlex
    cmd = ['ssh', '-o', 'ConnectTimeout=6', '-o', 'BatchMode=yes',
           '-p', '8022', PHONE, '--'] + [shlex.quote(a) for a in args]
    return run(cmd, 45)


def kaggle(account: str, *args: str) -> tuple[int, str]:
    return run([str(HERE / 'bin/kaggle-conta'), account] + list(args))


def ts() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def f143_summary(out: Path, fname: str = 'f143-calibracao.json', label: str = 'F143') -> str:
    """Le o JSON medido e aplica o gate PRE-REGISTRADO (sem renegociar)."""
    p = out / fname
    if not p.exists():
        return f'{label}: JSON de resultado NAO encontrado -- medicao pendente.'
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        rows = d['results']
        ctrl = {r['d']: r for r in rows if not r['anchored']}
        anch = {r['d']: r for r in rows if r['anchored']}
        parts = []
        ok = True
        for dim in sorted(ctrl):
            c, a = ctrl[dim], anch[dim]
            de = round(a['before']['ece'] - c['before']['ece'], 4)
            dv = round(a['before']['val_loss'] - c['before']['val_loss'], 4)
            da = round(a['before']['acc'] - c['before']['acc'], 4)
            passed = de <= -0.01 and dv <= 0.02 and da >= -0.01
            ok = ok and passed
            parts.append(f"d={dim}: dECE={de:+.4f} dval={dv:+.4f} dacc={da:+.4f} "
                         f"T={a['T']} ECEpos={a['after_temperature']['ece']} "
                         f"{'PASSA' if passed else 'NAO PASSA'}")
        return (f'{label} MEDIDO (corpus SimpleStories remap top-10000, 3 tamanhos, 9600 passos): '
                + ' | '.join(parts)
                + ('. GATE PRE-REGISTRADO PASSOU' if ok else '. GATE PRE-REGISTRADO NAO PASSOU — hipotese nao promovida, sem renegociar'))
    except Exception as e:
        return f'{label}: JSON presente mas falha ao aplicar gate: {type(e).__name__}: {e}'


def f160_summary() -> str:
    base = HERE / 'work/hybrid'
    if (base / 'f160-blocked.json').exists():
        return ('F160 BLOQUEADO por VRAM: smoke seq=4096 falhou; gate F98 NAO aplicado '
                '(nao e reprovacao). Ver f160-run.log.')
    vals = {}
    for m in ('learned', 'rope', 'alibi'):
        p = base / f'f160-{m}.json'
        if not p.exists():
            return 'F160: faltando braço ' + m
        try:
            vals[m] = json.loads(p.read_text(encoding='utf-8'))
        except Exception as e:
            return f'F160: JSON invalido de {m}: {e}'
    b = vals['learned']
    parts = []
    ok = True
    for m in ('rope', 'alibi'):
        dv = round(vals[m]['val_loss'] - b['val_loss'], 4)
        da = round(vals[m]['acc'] - b['acc'], 4)
        p = dv <= -0.02 and da >= -0.01
        ok = ok and p
        parts.append(f"{m}: dval={dv:+.4f} dacc={da:+.4f} VRAM={vals[m]['vram_bytes']} "
                     f"s={vals[m]['seconds']} {'PASSA' if p else 'NAO PASSA'}")
    return ('F160 MEDIDO em seq=4096 (4800 passos, d384, 19,66M tokens, seed42; '
            'threshold absoluto 1,6749 de F98 NAO comparavel nesta escala): '
            + ' | '.join(parts)
            + ('. GATE RELATIVO PASSOU' if ok else '. GATE RELATIVO NAO PASSOU'))


def record(fh, rec: dict) -> None:
    fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    fh.flush()


STATUS_SEEN: dict[str, str] = {}
STATUS_SINCE: dict[str, float] = {}
STUCK_WARNED: set[str] = set()
LAST_BEAT = 0.0


def main() -> None:
    global LAST_BEAT
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if EVENTS.exists():
        for line in EVENTS.read_text(errors='ignore').splitlines():
            try:
                rec = json.loads(line)
                # job fechado = complete rc==0 OU complete com bus publicado
                # (o rc=3 de "claimed nao encontrada" e esperado quando a
                # tarefa esta na fila; o numero ja foi para o #144).
                if rec.get('event') == 'complete' and (rec.get('rc') == 0 or rec.get('bus')):
                    done.add(rec.get('id'))
            except Exception:
                pass
    with EVENTS.open('a', encoding='utf-8') as f:
        record(f, {'event': 'start_v3', 'ts': ts(), 'jobs': len(JOBS)})
    while True:
        for job in JOBS:
            if job['id'] in done:
                continue
            ok = False
            if job['kind'] == 'file':
                ok = Path(job['path']).exists()
            elif job['kind'] == 'files3':
                ok = (Path(job['blocked']).exists()
                      or all(Path(p).exists() for p in job['paths']))
            if job['kind'] == 'kaggle':
                rc, status = kaggle('kuchiriel', 'kernels', 'status', job['slug'])
                # Auto-anuncio: qualquer mudança de status vira evento + bus.
                # Ninguém precisa ficar rodando `kaggle status` na mão.
                now = time.time()
                sig = status.strip().splitlines()[-1] if status.strip() else 'SEM_STATUS'
                prev = STATUS_SEEN.get(job['id'])
                if prev != sig:
                    STATUS_SEEN[job['id']] = sig
                    STATUS_SINCE[job['id']] = now
                    with EVENTS.open('a', encoding='utf-8') as f:
                        record(f, {'event': 'status_change', 'id': job['id'],
                                   'ts': ts(), 'from': prev, 'to': sig[:160]})
                    phone(BUS, f"POLLER {job['id']}: {prev or 'inicio'} -> {sig[:120]}", '--kind', 'msg')
                if ('QUEUED' in sig.upper()
                        and now - STATUS_SINCE.get(job['id'], now) > 3600
                        and job['id'] not in STUCK_WARNED):
                    STUCK_WARNED.add(job['id'])
                    phone(BUS, f"POLLER {job['id']}: Kaggle QUEUED ha >1h sem saida — verificar fila/conta; nao e erro de codigo.", '--kind', 'msg')
                erro = 'ERROR' in status.upper()
                ok = 'COMPLETE' in status.upper() or erro
                if erro:
                    _, lg = kaggle('kuchiriel', 'kernels', 'logs', job['slug'])
                    with EVENTS.open('a', encoding='utf-8') as f:
                        record(f, {'event': 'job_error', 'id': job['id'], 'ts': ts(),
                                   'log': lg[:400]})
                    _, bus = phone(BUS, f"JOB {job['id']} ERROU no Kaggle; numeros AINDA NAO medidos: " + lg[:220], '--kind', 'msg')
                    # nao fechar tarefa sem numero medido; so parar de retryar.
                    done.add(job['id'])
                    continue
                if ok:
                    out = HERE / 'work/hybrid' / ('kaggle-' + job['id'] + '-out')
                    out.mkdir(parents=True, exist_ok=True)
                    _, a = kaggle('kuchiriel', 'kernels', 'pull', job['slug'], '-p', str(out))
                    _, b = kaggle('kuchiriel', 'kernels', 'output', job['slug'], '-p', str(out))
                    if job['id'].startswith('F143-calibracao'):
                        job['reason'] = f143_summary(out)
                    elif job['id'].startswith('F144'):
                        job['reason'] = f143_summary(out, 'f144-robustez.json', 'F144')
                    else:
                        job['reason'] += ' | output=' + (b or a)[:120]
            if not ok:
                continue
            if job['id'] == 'F160-posicao4096':
                job['reason'] = f160_summary()
            with EVENTS.open('a', encoding='utf-8') as f:
                record(f, {'event': 'job_done', 'id': job['id'], 'ts': ts()})
            rc, out = phone(AW, 'complete', job['task'], '--principal', PRIN,
                            '--reason', job['reason'])
            # v2 bug: tarefa pode estar na fila, nao claimed. complete falha;
            # archive resolve e o numero ainda é publicado no bus.
            if rc != 0:
                rc2, out2 = phone(AW, 'archive', job['task'].split(': termux/')[-1],
                                  '--reason', job['reason'])
                out += ' | archive=' + out2[:120]
            _, bus = phone(BUS, job['reason'], '--kind', 'msg')
            with EVENTS.open('a', encoding='utf-8') as f:
                record(f, {'event': 'complete', 'id': job['id'], 'rc': rc,
                           'out': out[:200], 'bus': bus[:120]})
            done.add(job['id'])
        if time.time() - LAST_BEAT > 600:
            LAST_BEAT = time.time()
            with EVENTS.open('a', encoding='utf-8') as f:
                record(f, {'event': 'heartbeat', 'ts': ts(),
                           'jobs': len(JOBS), 'status': dict(STATUS_SEEN)})
        time.sleep(60)


if __name__ == '__main__':
    main()
