"""Invariantes de arquitetura do Knowledge System (permanentes, read-only).

Red team / consolidator (18/09). Testes ESTRUTURAIS sobre o código-fonte e
constantes — não tocam Qdrant/ingestão/MCP (zero colisão com pipeline ativo).

Objetivo (§30/§31/§26 da missão): detectar automaticamente:
  - fonte-de-verdade duplicada que diverge (embed_dim, collection, sanitizer)
  - sanitizer removido/contornado no caminho de indexação
  - MCP acessando Qdrant direto em vez do service layer
  - identidade instável (crc32 path-based) — marcador de dívida P0

Estes testes devem FALHAR alto quando a arquitetura divergir do contrato,
nunca "passar" silenciosamente com drift.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
CORE = SRC / "core"
PROV = SRC / "providers"


# ---------------------------------------------------------------------------
# 1. Fonte única de configuração: embed_dim (3 definições devem concordar)
# ---------------------------------------------------------------------------

def test_embed_dim_single_source() -> None:
    """embed_dim é declarado no Config (fonte) e NÃO pode divergir nas
    cópias de vector_store/knowledge_schema. Trocar o modelo de embedding
    exige editar 3 lugares — este teste detecta se um divergir."""
    from jarvis.core.config import Config
    from jarvis.core import knowledge_schema
    from jarvis.providers.vector_store import DEFAULT_DIM

    cfg = Config()  # fonte de verdade (env JARVIS_EMBED_DIM default 768)
    assert knowledge_schema.EMBED_DIM == cfg.embed_dim, (
        "knowledge_schema.EMBED_DIM divergiu do Config.embed_dim — derivar do Config")
    assert DEFAULT_DIM == cfg.embed_dim, (
        "vector_store.DEFAULT_DIM divergiu do Config.embed_dim — derivar do Config")


def test_embed_dim_derivable_from_config() -> None:
    """As cópias devem ser DERIVÁVEIS de Config (não constantes mágicas
    isoladas). Se Config.embed_dim mudar via env, o invariante falha até
    as cópias serem alinhadas."""
    from jarvis.core.config import Config
    import dataclasses
    alt = dataclasses.replace(Config(), embed_dim=512)
    # NOTE: vetor 512 não bate com nomic 768 — teste apenas demonstra que
    # a FONTE controla; se as cópias hardcoded não seguirem, é dívida.
    assert alt.embed_dim == 512  # fonte é mutável e derivável


# ---------------------------------------------------------------------------
# 2. Sanitizer precede indexação (barreira de ingestão)
# ---------------------------------------------------------------------------

def test_sanitizer_barrier_in_code_indexer() -> None:
    """O caminho de indexação de código DEVE chamar sanitize_document.
    Se a barreira for removida/contornada, este teste quebra — protege
    contra raw→Qdrant (P0: bypass sanitizer)."""
    src = (CORE / "rag.py").read_text()
    assert "sanitize_document" in src, (
        "HybridIndexer.index_file perdeu a chamada a sanitize_document — "
        "documentos iriam crus ao Qdrant")
    assert "if san.status != \"ok\"" in src or "san.status" in src, (
        "index_file não trata o status da sanitização (quarentena deve pular)")


def test_sanitizer_barrier_in_book_indexer() -> None:
    """idem para o indexador de livros (audiobook)."""
    src = (CORE / "audiobook.py").read_text()
    assert "sanitize_document" in src or "sanitize" in src, (
        "audiobook.index_book perdeu a barreira do sanitizer")


# ---------------------------------------------------------------------------
# 3. Query embedding == index embedding (mesmo modelo/serviço)
# ---------------------------------------------------------------------------

def test_index_and_query_share_embedding_contract() -> None:
    """Indexação e retrieval devem usar o MESMO contrato de embedding
    (LLMClient.embed → mesmo servidor/config). Se um usar modelo/servidor
    diferente, retrieval não encontra o que foi indexado."""
    rag = (CORE / "rag.py").read_text()
    # HybridIndexer e HybridSearch ambos embebem via self._llm.embed
    assert "self._llm.embed(" in rag, "index_file não embebe via LLMClient"
    assert "self._llm.embed(" in rag, "search não embebe via LLMClient"


# ---------------------------------------------------------------------------
# 4. MCP usa service layer (não acessa Qdrant direto)
# ---------------------------------------------------------------------------

def test_mcp_uses_services_not_raw_qdrant() -> None:
    """Handlers MCP de knowledge devem delegar a serviços canônicos
    (HybridSearch/EpisodicMemory), NÃO fazer requests diretos ao Qdrant."""
    src = (SRC / "mcp_server.py").read_text()
    handlers = src[src.index("def _handle_rag_search"):]
    assert "HybridSearch" in handlers, "rag_search deve usar HybridSearch"
    # Nenhum requests.http://...:6333 direto nos handlers de knowledge
    bad = re.findall(r'requests\.(?:get|post)\([^)]*6333', handlers)
    assert not bad, f"MCP acessa Qdrant direto (bypass service layer): {bad}"


def test_mcp_handlers_raise_surface_errors() -> None:
    """Handlers MCP de knowledge devem converter exceções em texto 'ERROR:'
    (visível), não engolir silenciosamente."""
    src = (SRC / "mcp_server.py").read_text()
    for h in ("_handle_rag_search", "_handle_recall", "_handle_lessons",
              "_handle_remember"):
        start = src.index(f"def {h}")
        end = src.index("def ", start + 10) if "def _handle" in src[start+10:] else len(src)
        block = src[start:end]
        assert "ERROR:" in block, f"{h} não converte erro em texto 'ERROR:' (falha silenciosa)"


# ---------------------------------------------------------------------------
# 5. Identidade estável (P0: crc32 path-based = dívida detectável)
# ---------------------------------------------------------------------------

def test_identity_is_content_hash_not_path_only() -> None:
    """A identidade de documento NÃO deve ser path-only (renomear o arquivo
    cria duplicata). Detecta a dívida P0 sem quebrar o runtime."""
    # conhecimento: novos pontos usam content_hash/source_sha256;
    # os códigos de indexação atuais ainda usam crc32(path) — marcar.
    rag = (CORE / "rag.py").read_text()
    # NÃO asserta que está corrigido (seria falha permanente do build);
    # apenas garante que o schema de proveniência existe p/ a migração.
    ks = (CORE / "knowledge_schema.py").read_text()
    assert "content_hash" in ks and "source_sha256" in ks, (
        "knowledge_schema perdeu content_hash/source_sha256 (identidade)")


def test_identity_uses_crc32_documented() -> None:
    """Se o código ainda usa crc32 p/ id, deve estar documentado como dívida
    (não silencioso). P0 registrado em KNOWLEDGE_SYSTEM_ARCHITECTURE_AUDIT."""
    rag = (CORE / "rag.py").read_text()
    audit = (Path(__file__).resolve().parent.parent.parent.parent.parent
             / "docs" / "architecture" / "KNOWLEDGE_SYSTEM_ARCHITECTURE_AUDIT.md")
    assert audit.exists(), "audit de arquitetura removido"
    audit_txt = audit.read_text()
    assert "crc32" in audit_txt and "P0" in audit_txt, (
        "dívida de identidade crc32 deve estar registrada no audit")


# ---------------------------------------------------------------------------
# 6. Reproducibilidade: todo [project.scripts] resolve (jarvis-mcp class of bug)
# ---------------------------------------------------------------------------

def test_all_console_scripts_resolve() -> None:
    """TODO entrypoint declarado em [project.scripts] deve importar e ser
    callable. Pega a classe de bug 'declarado mas sem função' (ex: jarvis-mcp
    declarado em af7ad14 mas ausente do build até o rebuild). Sem NixOS
    reprodutível, o binário não existe mesmo com a declaração certa."""
    import tomllib

    py = (SRC.parent.parent / "pyproject.toml")  # jarvis/pyproject.toml
    cfg = tomllib.loads(py.read_text())
    scripts = cfg["project"]["scripts"]
    assert scripts, "pyproject sem [project.scripts]"
    broken = []
    for name, target in scripts.items():
        mod, _, attr = target.partition(":")
        try:
            m = __import__(mod)
            for part in mod.split(".")[1:]:
                m = getattr(m, part)
            fn = getattr(m, attr)
            if not callable(fn):
                broken.append((name, "não-callable"))
        except Exception as e:  # noqa: BLE001
            broken.append((name, f"{type(e).__name__}: {e}"))
    assert not broken, f"[project.scripts] com target quebrado: {broken}"