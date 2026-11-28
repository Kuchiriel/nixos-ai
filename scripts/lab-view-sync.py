#!/usr/bin/env python3
"""lab-view-sync — integra dados medidos e controles touch no /lab.

Roda lab-data-sync.py, substitui o literal MACH_STAGES do index.html pelo
snippet gerado e injeta mobile-controls.js entre marcadores. Idempotente:
rodar de novo apenas troca o conteúdo entre marcadores.
"""
from __future__ import annotations
import re, subprocess
from pathlib import Path

T = Path('/home/nixos/projects/nixos-ai/tools/lab-timeline')
S = Path('/home/nixos/projects/nixos-ai/scripts')
B_BEGIN = '/* LAB_MOBILE_BEGIN */'
B_END = '/* LAB_MOBILE_END */'


def main() -> int:
    r = subprocess.run(['python3', str(S / 'lab-data-sync.py')],
                       capture_output=True, text=True, timeout=180)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        return r.returncode
    stages = (T / 'mach-stages.generated.js').read_text(encoding='utf-8')
    mobile = (T / 'mobile-controls.js').read_text(encoding='utf-8')
    p = T / 'index.html'
    html = p.read_text(encoding='utf-8')

    pat = re.compile(r'const MACH_STAGES=\[[\s\S]*?\n\];')
    if not pat.search(html):
        raise SystemExit('MACH_STAGES literal nao encontrado no index.html')
    html = pat.sub(stages.rstrip(), html, count=1)

    block = B_BEGIN + '\n<script>\n' + mobile + '\n</script>\n' + B_END
    if B_BEGIN in html and B_END in html:
        html = re.sub(re.escape(B_BEGIN) + r'[\s\S]*?' + re.escape(B_END),
                      lambda _: block, html, count=1)
    else:
        html = html.replace('</body>', block + '\n</body>', 1)
    p.write_text(html, encoding='utf-8')
    print(f'index.html atualizado: {len(stages.splitlines())} linhas de stages, '
          f'{len(mobile)} bytes de mobile controls')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
