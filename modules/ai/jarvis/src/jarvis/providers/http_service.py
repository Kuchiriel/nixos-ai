"""Utilitários HTTP compartilhados entre providers.

Padrão comum: health check com GET + timeout curto, retornando False
em caso de falha. Extraído de `Reranker`, `QdrantStore` e outros
providers que implementam `is_available` com o mesmo padrão.

Uso:
    from jarvis.providers.http_service import http_health_check

    class MyService:
        def is_available(self) -> bool:
            return http_health_check(f"{self._base}/health", timeout=2.0)
"""

from __future__ import annotations

import requests


def http_health_check(url: str, *, timeout: float = 2.0) -> bool:
    """Health check HTTP: GET com timeout curto, retorna False em falha.

    Útil para providers que precisam de `is_available()` com o mesmo
    padrão: tenta GET, retorna True se 200, False se qualquer erro.
    """
    try:
        resp = requests.get(url, timeout=timeout)
        return resp.status_code == 200
    except requests.RequestException:
        return False
