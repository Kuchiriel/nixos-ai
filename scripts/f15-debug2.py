#!/usr/bin/env python3
"""F15-debug2: comparar block_step (cache) contra blk.forward, bloco a bloco."""
from __future__ import annotations
import argparse, torch, torch.nn.functional as F
from pathlib import Path
SRC=Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--d",type=int,default=320)
    ap.add_argument("--steps",type=int,default=50); a=ap.parse_args()
    import runpy, sys
    m=runpy.run_path(str(SRC)); ScaleLM=m["ScaleLM"]
    # importar block_step do f15-decode
    sys.path.insert(0,"/home/nixos/projects/nixos-ai/scripts")
    import runpy
    fd=runpy.run_path("/home/nixos/projects/nixos-ai/scripts/f15-decode.py")
    torch.manual_seed(11)
    model=ScaleLM(65,a.d,"loop_spec").cuda(); model.eval()
    h=torch.randint(0,65,(1,16)).cuda()
    x=model.tok(h)+model.pos(torch.arange(16).cuda())
    with torch.no_grad():
        for i,blk in enumerate(model.blocks):
            spec = 2 <= i < 6
            got1=blk(x)  # forward normal (sem troca de adapters, usa q Parameter)
            # block_step manual com spec=False (Parameter)
            got2,_=fd["block_step"](blk,x,None,"last",0,False)
            print("block",i,"param-vs-manual",float((got1-got2).abs().max()),flush=True)
            x=got1

if __name__=="__main__": raise SystemExit(main())
