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
DIRECT = '/data/data/com.termux/files/home/bin/direct-msg'
PRIN = 'improver-termux-fast@termux:ses_e52816aa7ffe4zi1iV7cJ8mvtc'
MY_SID = 'ses_e52816aa7ffe4zi1iV7cJ8mvtc'  # sessionID explicito (codinome pode duplicar)
JOBS = [
    {
        'id': 'F168-dedup-variantes',
        'kind': 'file',
        'path': str(HERE / 'work/hybrid/f168-dedup.json'),
        'task': 'improver-termux-fast: termux/F168-corpus-dedup-variantes',
        'reason': 'F168: aguardando 3 corpora × 2 braços (960 passos, seed42)',
    },
    {
        'id': 'F167-escala-parametros',
        'kind': 'file',
        'path': str(HERE / 'work/hybrid/f167-escala.json'),
        'task': 'improver-termux-fast: termux/F167-corpus-escala-parametros',
        'reason': 'F167: aguardando 12 bracos (d704/960/1216 × seed42/43 × controle/binario)',
    },
    {
        'id': 'F166-corpus-mais-passos',
        'kind': 'file',
        'path': str(HERE / 'work/hybrid/f166-corpus.json'),
        'task': 'improver-termux-fast: termux/F166-corpus-mais-passos',
        'reason': 'F166: aguardando 12 braços (3 tamanhos × 2 sementes × 2 condições)',
    },
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


def ping(text: str, kind: str = 'msg') -> tuple[str, str]:
    """Publica no bus E injeta na sessao do dono pelo direct-msg.

    O plugin consome direct-msg.jsonl no idle e injeta com synthetic —
    mesmo caminho usado pelo auto-wake. Texto curto, sessionID explicito.
    """
    _, bus = phone(BUS, text[:1200], '--kind', 'status')
    rc, dm = phone(DIRECT, MY_SID, text[:800], '--kind', kind,
                   '--from', 'poller-async')
    return bus[:120], f'rc={rc} {dm[:120]}'


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


def f168_summary() -> str:
    p = HERE / 'work/hybrid/f168-dedup.json'
    if not p.exists():
        return 'F168: JSON ainda nao existe'
    try:
        rows = json.loads(p.read_text(encoding='utf-8'))['results']
        parts, ok = [], True
        for r in rows:
            dv = round(r['binary']['val_loss'] - r['control']['val_loss'], 4)
            da = round(r['binary']['acc'] - r['control']['acc'], 4)
            good = dv <= 0.02 and da >= -0.01
            ok = ok and good
            parts.append(f"{r['corpus']} {dv:+.4f}/{da:+.4f}")
        return ('F168 MEDIDO (3 corpora, 960 passos, seed42): ' + ' | '.join(parts)
                + ('. GATE 3/3 PASSOU' if ok else '. GATE NAO PASSOU — sem renegociar'))
    except Exception as e:
        return f'F168: falha ao aplicar gate: {type(e).__name__}: {e}'


def f167_summary() -> str:
    p = HERE / 'work/hybrid/f167-escala.json'
    if not p.exists():
        return 'F167: JSON ainda nao existe'
    try:
        rows = json.loads(p.read_text(encoding='utf-8'))['results']
        parts, ok = [], True
        for seed in (42, 43):
            for dim in (704, 960, 1216):
                r = next(x for x in rows if x['seed'] == seed and x['d'] == dim)
                dv = round(r['binary']['val_loss'] - r['control']['val_loss'], 4)
                da = round(r['binary']['acc'] - r['control']['acc'], 4)
                good = dv <= 0.02 and da >= -0.01
                ok = ok and good
                parts.append(f's{seed}/d{dim} {dv:+.4f}/{da:+.4f} '
                             f'VRAM={r["binary"]["vram"]}s')
        return ('F167 MEDIDO (GPU, 960 passos, 20M ids): ' + ' | '.join(parts)
                + ('. GATE PASSOU' if ok else '. GATE NAO PASSOU — sem renegociar'))
    except Exception as e:
        return f'F167: falha ao aplicar gate: {type(e).__name__}: {e}'


def f166_summary() -> str:
    p = HERE / 'work/hybrid/f166-corpus.json'
    if not p.exists():
        return 'F166: JSON ainda nao existe'
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        rows = d['results']
        parts, ok = [], True
        for seed in (42, 43):
            for dim in (192, 384, 768):
                r = next(x for x in rows if x['seed'] == seed and x['d'] == dim)
                dv = round(r['binary']['val_loss'] - r['control']['val_loss'], 4)
                da = round(r['binary']['acc'] - r['control']['acc'], 4)
                p = dv <= 0.02 and da >= -0.01
                ok = ok and p
                parts.append(f's{seed}/d{dim} {dv:+.4f}/{da:+.4f}')
        return ('F166 MEDIDO (960 passos, corpus dedup8 20M, 2 sementes): '
                + ' | '.join(parts)
                + ('. GATE 3/3x2 PASSOU' if ok else '. GATE NAO PASSOU — sem renegociar'))
    except Exception as e:
        return f'F166: falha ao aplicar gate: {type(e).__name__}: {e}'


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


def write_live(done: set) -> None:
    """Estado maquina legivel para o /lab mostrar o que roda onde."""
    def tail_step(name: str) -> dict:
        p = HERE / 'work/hybrid' / f'{name}-run.log'
        if not p.exists():
            return {'log': 'ausente'}
        lines = p.read_text(errors='ignore').splitlines()[-1:] or ['']
        try:
            r = json.loads(lines[0])
            return {'step': r.get('step'), 'loss': r.get('loss'),
                    'seed': r.get('seed'), 'd': r.get('d')}
        except Exception:
            return {'tail': lines[0][:160]}
    jobs = []
    for job in JOBS:
        jobs.append({'id': job['id'],
                     'done': job['id'] in done,
                     'kaggle': STATUS_SEEN.get(job['id'], ''),
                     'file': bool(Path(job.get('path', '')).exists()) if job.get('path') else None})
    live = {'ts': ts(), 'epoch': int(time.time()), 'jobs': jobs,
            'local': {'f166': Path(HERE / 'work/hybrid/f166-corpus.json').exists(),
                      'f167': tail_step('f167'), 'f168': tail_step('f168'),
                      'f160': tail_step('f160')},
            'queue': str(HERE / 'work/hybrid/async-events.jsonl')}
    p = HERE / 'work/hybrid/live-status.json'
    p.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding='utf-8')


def record(fh, rec: dict) -> None:
    fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    fh.flush()


STATUS_SEEN: dict[str, str] = {}
STATUS_SINCE: dict[str, float] = {}
STUCK_WARNED: set[str] = set()
LAST_BEAT = 0.0
LAST_PING = 0.0


def main() -> None:
    global LAST_BEAT, LAST_PING
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
                    ping(f"POLLER {job['id']}: {prev or 'inicio'} -> {sig[:120]}")
                if ('QUEUED' in sig.upper()
                        and now - STATUS_SINCE.get(job['id'], now) > 3600
                        and job['id'] not in STUCK_WARNED):
                    STUCK_WARNED.add(job['id'])
                    ping(f"POLLER {job['id']}: Kaggle QUEUED ha >1h sem saida — verificar fila/conta; nao e erro de codigo.")
                erro = 'ERROR' in status.upper()
                ok = 'COMPLETE' in status.upper() or erro
                if erro:
                    _, lg = kaggle('kuchiriel', 'kernels', 'logs', job['slug'])
                    with EVENTS.open('a', encoding='utf-8') as f:
                        record(f, {'event': 'job_error', 'id': job['id'], 'ts': ts(),
                                   'log': lg[:400]})
                    bus, dm = ping(f"JOB {job['id']} ERROU no Kaggle; numeros AINDA NAO medidos: " + lg[:220])
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
            if job['id'] == 'F168-dedup-variantes':
                job['reason'] = f168_summary()
            elif job['id'] == 'F160-posicao4096':
                job['reason'] = f160_summary()
            elif job['id'] == 'F166-corpus-mais-passos':
                job['reason'] = f166_summary()
            elif job['id'] == 'F167-escala-parametros':
                job['reason'] = f167_summary()
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
            bus, dm = ping(job['reason'])
            with EVENTS.open('a', encoding='utf-8') as f:
                record(f, {'event': 'complete', 'id': job['id'], 'rc': rc,
                           'out': out[:200], 'bus': bus[:120], 'direct': dm[:120]})
            done.add(job['id'])
        if time.time() - LAST_BEAT > 600:
            LAST_BEAT = time.time()
            with EVENTS.open('a', encoding='utf-8') as f:
                record(f, {'event': 'heartbeat', 'ts': ts(),
                           'jobs': len(JOBS), 'status': dict(STATUS_SEEN)})
            if time.time() - LAST_PING > 1800:
                LAST_PING = time.time()
                ping('POLLER heartbeat ' + ts() + ' :: ' + json.dumps(STATUS_SEEN)[:400])
        write_live(done)
        time.sleep(60)


if __name__ == '__main__':
    main()
