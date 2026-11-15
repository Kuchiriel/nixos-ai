#!/usr/bin/env python3
"""deliver.py — entrega canonica (usada pelo hub para nao duplicar caminho).

(15/11, crouton-alpha) O hub injetava prompt por POST proprio em
/api/session/<id>/prompt — um TERCEIRO caminho de injecao, alem do
coord_roster.send_message (Telegram /to) e do plugin agent-wake. Isso
duplicava guard de intrusao, cooldown, dedupe e o registro no bus.
Aqui o hub chama exatamente o caminho da casa.

uso: deliver.py <agente> <texto> [--note]
"""
import json
import sys

sys.path.insert(0, "/home/nixos/projects/nixos-ai/modules/ai/jarvis/src")
from jarvis.core.comms import deliver  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "error": "uso: deliver.py <agente> <texto> [--note]"}))
        return 1
    name, text = sys.argv[1], sys.argv[2]
    note = "--note" in sys.argv[3:]
    try:
        ok, detail = deliver(name, text, request=not note)
        print(json.dumps({"ok": bool(ok), "detail": str(detail)[:1200]}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)[:300]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
