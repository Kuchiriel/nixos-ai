#!/usr/bin/env python3
"""dat_probe.py — sonda do APPEARANCES .dat do CLIENT (protobuf moderno).

Uso (via nix develop do nixos-ai — PYTHONPATH e stripado no shell):
  cd ~/projects/nixos-ai && nix develop --command python3 scripts/dat_probe.py 918 55332
  nix develop --command python3 scripts/dat_probe.py --flags 1950

O que faz:
  - default: id -> fg/sprites/nome (existencia + visual)
  - --flags: lista TODOS os campos de flags nao-default do id
    (unpass/unmove/bank/height/... — o juiz de walkable/pickupable)
  - --ground N: raio N ao redor do spawn (533,450) lista grounds

Fonte das descobertas (16/10): 381-384 = paredes core (unpass True);
385 unico cave-walkable; 1950 rampa unpass False + height 8;
 ThingFlagAttrFloorChange nunca e setado no caminho protobuf.
"""
import sys, glob

sys.path.insert(0, '/home/nixos/projects/canary-official/data-sandbox/tools/reskin')
import appearances_pb2 as ap

DAT = glob.glob('/home/nixos/projects/otclient/data/things/1525/appearances-*.dat')
DAT = [f for f in DAT if not any(x in f for x in ('.bak', 'flagsync', 'ghost'))]


def load():
    dat = ap.Appearances()
    with open(DAT[0], 'rb') as f:
        dat.ParseFromString(f.read())
    return {a.id: a for a in dat.object}


def sprites_de(fg):
    try:
        si = fg.sprite_info
        return len(list(si.sprite_id)) if si else 0
    except Exception:
        return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    modo_flags = '--flags' in sys.argv
    m = load()
    if not args:
        print(f"{len(m)} objects; use: dat_probe.py [--flags] <id>...")
        return
    for gid in [int(a) for a in args]:
        a = m.get(gid)
        if not a:
            print(f"  {gid}: AUSENTE")
            continue
        if modo_flags:
            print(f"--- {gid} ---")
            for f in ap.AppearanceFlags.DESCRIPTOR.fields:
                v = getattr(a.flags, f.name, None)
                if v not in (None, False, 0, '', 0.0, []):
                    print(f"  {f.name} = {v}")
        else:
            ns = len(a.frame_group)
            spr = sum(sprites_de(fg) for fg in a.frame_group)
            print(f"  {gid}: fg={ns} sprites={spr} unpass={a.flags.unpass} "
                  f"unmove={a.flags.unmove} name={(a.name or '')[:24]}")


if __name__ == '__main__':
    main()
