#!/usr/bin/env python3
"""lab-view-sync — integra dados medidos, estado ao vivo e controles no /lab."""
from __future__ import annotations
import json, re, subprocess
from pathlib import Path

H = Path('/home/nixos')
T = H / 'projects/nixos-ai/tools/lab-timeline'
S = H / 'projects/nixos-ai/scripts'
LIVE = H / 'work/hybrid/live-status.json'
B_BEGIN, B_END = '/* LAB_MOBILE_BEGIN */', '/* LAB_MOBILE_END */'
V_BEGIN, V_END = '/* LAB_LIVE_BEGIN */', '/* LAB_LIVE_END */'


def block(marker_begin: str, marker_end: str, inner: str) -> str:
    return f'{marker_begin}\n<script>\n{inner}\n</script>\n{marker_end}'


def main() -> int:
    r = subprocess.run(['python3', str(S / 'lab-data-sync.py')],
                       capture_output=True, text=True, timeout=180)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        return r.returncode
    stages = (T / 'mach-stages.generated.js').read_text(encoding='utf-8')
    mobile = (T / 'mobile-controls.js').read_text(encoding='utf-8')
    live_js = (T / 'lab-live.js').read_text(encoding='utf-8')
    status = json.loads(LIVE.read_text(encoding='utf-8')) if LIVE.exists() else {}
    live_data = 'window.LAB_LIVE=' + json.dumps(status, ensure_ascii=False) + ';\n'

    p = T / 'index.html'
    html = p.read_text(encoding='utf-8')
    # Remove a view legada e textos inúteis do RODAPÉ na fonte (não só via JS).
    html = re.sub(r'<details[^>]*>\s*<summary[^>]*>Ver visão antiga[\s\S]*?</details>',
                  '', html, count=1)
    html = re.sub(r'<p[^>]*>[^<]*(Inspiração de visualização|Frentes anteriores a F32)[^<]*</p>',
                  '', html)
    pat = re.compile(r'const MACH_STAGES=\[[\s\S]*?\n\];')
    if not pat.search(html):
        raise SystemExit('MACH_STAGES nao encontrado')
    html = pat.sub(stages.rstrip(), html, count=1)

    # Dados do poller + painel ao vivo (sempre reescritos entre marcadores).
    vblock = block(V_BEGIN, V_END, live_data + live_js)
    if V_BEGIN in html and V_END in html:
        html = re.sub(re.escape(V_BEGIN) + r'[\s\S]*?' + re.escape(V_END),
                      lambda _: vblock, html, count=1)
    else:
        html = html.replace('</body>', vblock + '\n</body>', 1)

    mblock = block(B_BEGIN, B_END, mobile)
    if B_BEGIN in html and B_END in html:
        html = re.sub(re.escape(B_BEGIN) + r'[\s\S]*?' + re.escape(B_END),
                      lambda _: mblock, html, count=1)
    else:
        html = html.replace('</body>', mblock + '\n</body>', 1)

    if 'id="labLiveHost"' not in html:
        html = re.sub(r'<body[^>]*>', lambda m: m.group(0) +
                      '<div id="labLiveHost"></div>', html, count=1)
    if 'LAB_AUTOREFRESH' not in html:
        html = html.replace('</body>',
                            '<script>/* LAB_AUTOREFRESH */setTimeout(function(){' +
                            'sessionStorage.setItem("labScroll",String(window.scrollY));' +
                            'location.reload();},20000);window.addEventListener("load",' +
                            'function(){window.scrollTo(0,Number(sessionStorage.getItem("labScroll")||0));});' +
                            '</script></body>', 1)
    p.write_text(html, encoding='utf-8')
    print(f'index.html: {len(stages.splitlines())} linhas stages, '
          f'{len(live_js)} bytes painel vivo, {len(mobile)} bytes touch')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
