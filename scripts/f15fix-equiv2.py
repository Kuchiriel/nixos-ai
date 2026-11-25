#!/usr/bin/env python3
"""F15-fix: equivalencia contra forward CAUSAL (mesma info do decode)."""
import argparse, json, torch
from pathlib import Path
SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--d",type=int,default=320)
    ap.add_argument("--mode",default="per_loop"); ap.add_argument("--out",required=True)
    a=ap.parse_args()
    import runpy
    ScaleLM=runpy.run_path(str(SRC))["ScaleLM"]
    torch.manual_seed(3); m=ScaleLM(65,a.d,"loop_spec").cuda(); m.eval()
    ids=torch.randint(0,65,(1,12)).cuda()
    with torch.no_grad():
        full=m(ids,causal=True)[0,-1,:].float()
        st={"caches":{},"u":None}
        for pos in range(12):
            out=m.forward_cached(ids[:,pos:pos+1],pos,st,a.mode)
        diff=float((full-out[0,0,:].float()).abs().max())
    r={"mode":a.mode,"max_logit_diff":diff,"pass":diff<1e-2}
    Path(a.out).write_text(json.dumps(r,indent=2)+"\n")
    print("RESULT "+json.dumps(r),flush=True)
if __name__=="__main__": raise SystemExit(main())
