"""JARVIS — sistema de IA local para NixOS.

Separação de responsabilidades:
- core:    roteamento, intenções, memória, ferramentas (sem acoplamento a serviços)
- providers: adaptadores para llama.cpp, Qdrant, Whisper, Kokoro, wakeword
- cli:     interfaces de linha de comando
- daemon:  servidor IPC (FastAPI sobre unix socket) — fase posterior
"""

__version__ = "0.1.0"
"""Version string for the JARVIS package."""