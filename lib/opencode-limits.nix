# lib/opencode-limits.nix — política de headroom de contexto p/ o opencode
#
# POR QUE (02/11, bug "Bad Request" 400 no NVIDIA/minimax):
# o opencode calcula o limiar de auto-compactação assim
# (packages/opencode/src/session/overflow.ts, v1.18.34 e v1.19.5):
#
#   usable = limit.input ? limit.input - reserved
#                          : context - maxOutputTokens
#   reserved       = compaction.reserved ?? min(20000, maxOutputTokens)
#   maxOutputTokens = min(limit.output, 32000)   [transform.ts OUTPUT_TOKEN_MAX]
#
# As APIs OpenAI-compatíveis validam prompt_tokens + max_tokens ≤ context.
# SEM limit.input, usable = context - maxOutputTokens = o TETO EXATO da API
# (folga ZERO). E o opencode só checa o overflow com a contagem do turno
# ANTERIOR (session/prompt.ts:1164) → o request seguinte estoura o teto →
# HTTP 400 "Bad Request" (não retryável) e compactação tardia.
# Medido no NIM: 262146 tokens = 2 acima do teto de 262144.
#
# FIX: declarar limit.input = usable + reserved, com
#      usable = promptCeiling - headroom
# → o limiar de compactação fica `headroom` tokens ABAIXO do teto real
#   (cobre o crescimento de 1 turno) e NUNCA fica mais permissivo que o
#   limiar anterior (monotonicamente seguro: usable ≤ context - maxTokens).
{
  lib,
}: let
  # Constantes do runtime do opencode (mesmas em v1.18.34 e v1.19.5).
  outputTokenMax = 32000; # provider/transform.ts OUTPUT_TOKEN_MAX
  compactionBuffer = 20000; # session/overflow.ts COMPACTION_BUFFER

  # Headroom default: mesma ordem do COMPACTION_BUFFER do opencode.
  defaultHeadroom = 20000;
in {
  inherit outputTokenMax compactionBuffer defaultHeadroom;

  # limits { context, output, headroom ? defaultHeadroom }
  #   → { maxTokens, reserved, promptCeiling, margin, usable, input }
  limits = {
    context,
    output,
    headroom ? defaultHeadroom,
  }: let
    maxTokens = lib.min output outputTokenMax;
    reserved = lib.min compactionBuffer maxTokens; # default upstream (compaction.reserved unset)
    promptCeiling = context - maxTokens; # prompt + max_tokens ≤ context
    # Budget pequeno não pode perder 20k de prompt: headroom proporcional
    # (1/4 do teto), com piso de 2048 tokens.
    margin = lib.min headroom (lib.max 2048 (promptCeiling / 4));
    usable = lib.max 0 (promptCeiling - margin);
  in {
    inherit maxTokens reserved promptCeiling margin usable;
    # null quando não existe teto de prompt utilizável (context ≤ maxTokens):
    # o opencode cai no comportamento padrão (sem limit.input).
    input = if promptCeiling > 0 then usable + reserved else null;
  };
}
