"""Testes do plugin do opencode (home-manager/files/opencode/plugins/memory.js).

O plugin é o HARNESS das regras de memória/coordenação: se ele falha, o agente
volta a tropeçar no mesmo problema (a regra vira disciplined, não sistema).
Por isso ele tem teste — não havia nenhum (o bug do regex de root-delete só
apareceu quando a injeção nova foi escrita).

Cobre:
- deny de root-delete (a regex é sutil: NÃO pode casar com /tmp/x);
- injeção mínima no system prompt (a regra do resgate);
- A/B: OPENCODE_NO_REHYDRATE_INJECT=1 desliga a injeção;
- triagem na compactação: as guardas de coordenação são PINADAS no contexto.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "home-manager/files/opencode/plugins/memory.js"
NODE = "node"


def run_plugin(env_extra: dict[str, str] | None = None, body: str = "") -> dict:
    """Chama o plugin no node e devolve o JSON do stdout."""
    import os

    env = dict(os.environ)
    env.update(env_extra or {})
    script = f"""
import('file://{PLUGIN}').then(async (m) => {{
  const hooks = await m.MemoryOpenCodePlugin();
  const out = {{}};
  {body}
  console.log(JSON.stringify(out));
}});
"""
    proc = subprocess.run([NODE, "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0, f"node falhou: {proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_plugin_file_exists_and_is_valid_js():
    proc = subprocess.run([NODE, "--check", str(PLUGIN)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_root_delete_is_denied():
    """`rm -rf /` e `rm -rf ~` precisam ser barrados."""
    body = """
  for (const cmd of ['rm -rf /', 'rm -rf ~', 'rm -rf / ', 'sudo rm -rf /', 'rm -fr /',
                     'rm -Rf /', 'rm -fR /', 'rm -rf /*', 'rm -rf --no-preserve-root /']) {
    const o = {args: {command: cmd}};
    await hooks['tool.execute.before']({tool: 'bash'}, o);
    out[cmd] = o.args.command.startsWith('echo') ? 'DENIED' : 'PASSED';
  }
"""
    out = run_plugin(body=body)
    for cmd in ("rm -rf /", "rm -rf ~", "rm -rf / ", "sudo rm -rf /", "rm -fr /",
                "rm -Rf /", "rm -fR /", "rm -rf /*", "rm -rf --no-preserve-root /"):
        assert out[cmd] == "DENIED", f"{cmd} passou pelo deny ({out[cmd]})"


def test_scoped_delete_passes():
    """Delete de path escopado é legítimo (a regra do dono: escopado passa)."""
    body = """
  for (const cmd of ['rm -rf /tmp/opencode/x', 'rm -rf /home/nixos/projects/foo/bar', 'rm -rf ./build']) {
    const o = {args: {command: cmd}};
    await hooks['tool.execute.before']({tool: 'bash'}, o);
    out[cmd] = o.args.command.startsWith('echo') ? 'DENIED' : 'PASSED';
  }
"""
    out = run_plugin(body=body)
    for cmd in out:
        assert out[cmd] == "PASSED", f"{cmd} foi barrado por engano"


def test_system_prompt_gets_the_rehydrate_rule():
    """A regra vai MESCLADA no system prompt (1 bloco só).

    Push cria um 2º system message e o template do modelo aborta com
    "System message must be at the beginning" (erro real na 1ª medição).
    """
    body = """
  const o = {system: ['base']};
  await hooks['experimental.chat.system.transform']({sessionID: 's'}, o);
  out.blocks = o.system.length;
  out.text = o.system[0];
"""
    out = run_plugin(body=body)
    assert out["blocks"] == 1, "a injeção não pode criar um 2º system message"
    assert "jarvis_rehydrate" in out["text"]
    assert "claim" in out["text"]
    # injeção MINUTA: contexto é recurso finito (2510.05381)
    assert len(out["text"]) < 1500, f"injeção grande demais: {len(out['text'])} chars"


def test_system_injection_can_be_disabled_for_ab():
    body = """
  const o = {system: ['base']};
  await hooks['experimental.chat.system.transform']({sessionID: 's'}, o);
  out.blocks = o.system.length;
"""
    out = run_plugin({"OPENCODE_NO_REHYDRATE_INJECT": "1"}, body=body)
    assert out["blocks"] == 1, "com o flag de A/B a injeção não pode acontecer"


def test_compaction_pins_the_coordination_guards():
    """Na compactação, as guardas vão PINADAS (2608.22752: resumir quebra regras)."""
    body = """
  const o = {context: []};
  await hooks['experimental.session.compacting']({sessionID: 's'}, o);
  out.text = o.context[0];
"""
    out = run_plugin(body=body)
    txt = out["text"]
    assert "jarvis_rehydrate" in txt
    assert "agent-roster.py claim" in txt
    assert "--note" in txt and "--to" in txt and "--cancel" in txt
    assert "nunca wtype/focus" in txt
