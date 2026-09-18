# INDEX — docs/architecture

> Entrypoint do diretório. Cada doc com wikilink coerente; mapas .mmd são Mermaid.

## ADRs (decisões de arquitetura)
- [[ADR-001-agent-platform|ADR-001-agent-platform.md]] — plataforma de agentes (workflows, orquestrador)
- [[ADR-002-memory-layers|ADR-002-memory-layers.md]] — episódica ≠ RAG ≠ vault (3 camadas)
- [[ADR-003-persona-layers|ADR-003-persona-layers.md]] — personas e framing
- [[ADR-004-routing-policy|ADR-004-routing-policy.md]] — roteamento de modelos (tiers, cascata)

## Mapas e visões
- [[ARCHITECTURE.mmd|ARCHITECTURE.mmd]] — diagrama Mermaid do sistema
- [[SELF-IMPROVEMENT-LOOP.mmd|SELF-IMPROVEMENT-LOOP.mmd]] — loop de auto-melhoria
- [[system-overview|system-overview.md]] — visão geral
- [[SYSTEM-MAP|SYSTEM-MAP.md]] — 🗺️ mapa de primeira leitura (topologia repos + camadas + código)

## Componentes
- [[agent-harness|agent-harness.md]] — harness do agente (camadas, sensores)
- [[nightwatch-components|nightwatch-components.md]] — componentes do nightwatch
- [[mcp-integration|mcp-integration.md]] — integração MCP
- [[context-engineering|context-engineering.md]] — context engineering aplicado
- [[rag-improvements|rag-improvements.md]] — melhorias do RAG híbrido

## Domínio e otimização
- [[llama-cpp-tuning|llama-cpp-tuning.md]] — tuning do llama.cpp (flags, VRAM)
- [[slm-techniques|slm-techniques.md]] — técnicas para modelos pequenos
- [[jarvis-comparison|jarvis-comparison.md]] — comparação JARVIS × alternativas
- [[monorepo-schema|monorepo-schema.md]] — schema do monorepo
- [[mission-consolidation|mission-consolidation.md]] — consolidação de missões
- [[platform-assessment|platform-assessment.md]] — avaliação da plataforma
- [[pillar-diagnostic|pillar-diagnostic.md]] — diagnóstico de pilares

## Auditoria
- [[KNOWLEDGE_SYSTEM_ARCHITECTURE_AUDIT]] — contratos e dependências do knowledge system (read-only)
