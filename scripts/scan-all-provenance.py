#!/usr/bin/env python3
"""Map every code_index path to the last git commit that touched its file."""
import collections, json, subprocess, urllib.request

Q = 'http://127.0.0.1:6333'


def req(method, path, body=None, timeout=240):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(Q + path, data=data, method=method,
                               headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read())


def paths():
    out, offset = [], None
    while True:
        body = {'limit': 1000, 'with_payload': ['path'], 'with_vector': False}
        if offset:
            body['offset'] = offset
        res = req('POST', '/collections/code_index/points/scroll', body)['result']
        out.extend(str((p.get('payload') or {}).get('path', '')) for p in res['points'])
        offset = res.get('next_page_offset')
        if not offset:
            break
    return out


def repo_root(p):
    parts = p.split('/')
    if len(parts) >= 5 and parts[1:3] == ['home', 'nixos']:
        if parts[3] == 'projects' and len(parts) >= 5:
            return '/'.join(parts[:5])
        if parts[3] in ('Books', 'work'):
            return '/'.join(parts[:4])
    return ''


def main():
    ps = paths()
    cnt = collections.Counter(ps)
    groups = collections.defaultdict(list)
    for p in cnt:
        r = repo_root(p)
        if r:
            groups[r].append(p)
    mapping, stats = {}, []
    for root, plist in sorted(groups.items(), key=lambda kv: -sum(cnt[p] for p in kv[1])):
        try:
            if subprocess.run(['git', '-C', root, 'rev-parse', '--git-dir'],
                              capture_output=True, timeout=10).returncode != 0:
                raise RuntimeError('sem git')
            log = subprocess.run(['git', '-C', root, 'log', '--format=COMMIT %H',
                                  '--name-only', '--no-renames', '-n', '3000'],
                                 capture_output=True, text=True, timeout=120).stdout.splitlines()
        except Exception as e:
            stats.append({'repo': root, 'paths': len(plist),
                          'points': sum(cnt[p] for p in plist),
                          'error': type(e).__name__ + ':' + str(e)[:60]})
            continue
        last, commit = {}, None
        for line in log:
            if line.startswith('COMMIT '):
                commit = line[7:]
            elif line.strip() and line not in last:
                last[line.strip()] = commit
        n = 0
        for p in plist:
            rel = p[len(root) + 1:]
            if rel in last:
                mapping[p] = last[rel]
                n += 1
        stats.append({'repo': root, 'paths': len(plist),
                      'points': sum(cnt[p] for p in plist), 'mapped_paths': n,
                      'mapped_points': sum(cnt[p] for p in plist if p in mapping)})
    total_points = sum(cnt.values())
    mapped_points = sum(cnt[p] for p in mapping)
    print(json.dumps({'points': total_points, 'unique_paths': len(cnt),
                      'mapped_points': mapped_points,
                      'coverage': round(mapped_points / total_points, 3),
                      'repos': stats[:15]}, indent=2, ensure_ascii=False))
    with open('/home/nixos/projects/nixos-ai/scripts/provenance-map.json', 'w') as f:
        json.dump(mapping, f, indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
