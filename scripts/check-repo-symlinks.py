#!/usr/bin/env python3
"""check-repo-symlinks.py — symlink absoluto dentro do repo quebra o eval puro.

Proposito: um symlink com destino absoluto (tipicamente /nix/store) dentro do
repo faz `nix build` falhar em pure eval com "access to absolute path ... is
forbidden". Isso ja custou dois rebuilds em 13/11: o home-manager gerenciou
arquivos cujo diretorio em ~/.config era um symlink para o repo, e a ativacao
escreveu os links do store dentro da arvore. O check roda antes do rebuild e
aponta o arquivo e o destino, em vez de deixar o erro aparecer no eval.

Uso:
    python3 scripts/check-repo-symlinks.py [repo] [--quiet]

    repo     raiz do repo git (default: pai deste script)
    --quiet  so imprime quando ha violacao

Exemplo:
    python3 scripts/check-repo-symlinks.py ~/projects/nixos-ai
    # exit 0 = limpo; exit 1 = lista de symlinks absolutos; exit 2 = nao e repo

Contrato: le apenas o indice e os untracked do git (respeita .gitignore, entao
`result` e afins nao contam). Nao escreve nada.
"""
import os
import subprocess
import sys


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def tracked_symlinks(repo):
    out = git(repo, "ls-files", "-s", "-z").stdout
    paths = []
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        fields = meta.split()
        if len(fields) >= 2 and fields[0] == "120000":
            paths.append(path)
    return paths


def untracked_symlinks(repo):
    out = git(repo, "ls-files", "-o", "--exclude-standard", "-z").stdout
    paths = []
    for path in out.split("\0"):
        if path and os.path.islink(os.path.join(repo, path)):
            paths.append(path)
    return paths


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in argv[1:]
    repo = os.path.abspath(args[0]) if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        print(f"check-repo-symlinks: {repo} nao e um repo git", file=sys.stderr)
        return 2

    offenders = []
    for path in sorted(set(tracked_symlinks(repo) + untracked_symlinks(repo))):
        full = os.path.join(repo, path)
        try:
            target = os.readlink(full)
        except OSError:
            continue
        if os.path.isabs(target):
            offenders.append((path, target))

    if offenders:
        print(f"check-repo-symlinks: {len(offenders)} symlink(s) absoluto(s) em {repo}")
        for path, target in offenders:
            print(f"  {path} -> {target}")
        print("eval puro falha nesses caminhos; substitua por arquivo regular ou link relativo")
        return 1

    if not quiet:
        print(f"check-repo-symlinks: limpo ({repo})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
