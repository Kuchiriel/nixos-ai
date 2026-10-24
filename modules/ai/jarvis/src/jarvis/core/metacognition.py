# metacognition.py — Metacognição para JARVIS (v23+)
# Monitor de confiança, auto-avaliação pré-fala, detecção de incerteza,
# auto-correção online. Integra com EpisodicMemory, HybridSearch, tools.

from __future__ import annotations
import time
import threading
import json
import math
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple
from collections import deque
import threading

# ── Constantes ──────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD = 0.65      # Abaixo disso = incerto
HIGH_CONFIDENCE = 0.85           # Acima = confiante
UNCERTAINTY_WINDOW = 5           # Tokens para média móvel
UNCERTAINTY_THRESHOLD = 0.4      # Score de incerteza alto
MAX_HISTORY = 1000               # Histórico de confiança

# ── Estruturas de Dados ────────────────────────────────────────────
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple
from collections import deque
import threading
import time
import math
import json
import random

@dataclass
class ConfidenceSample:
    """Amostra de confiança por token/resposta."""
    timestamp: float
    text: str
    confidence: float           # 0.0 - 1.0
    uncertainty: float          # 1.0 - confidence
    source: str                 # 'llm_logprob', 'heuristic', 'self_eval'
    tokens: int = 0
    tool_calls: int = 0
    latency_ms: float = 0.0

@dataclass
class MetacognitionState:
    """Estado global da metacognição."""
    history: deque = field(default_factory=lambda: deque(maxlen=1000))
    uncertainty_window: deque = field(default_factory=lambda: deque(maxlen=UNCERTAINTY_WINDOW))
    total_responses: int = 0
    low_confidence_count: int = 0
    self_corrections: int = 0
    aborted_responses: int = 0
    last_confidence: float = 1.0
    last_uncertainty: float = 0.0
    
    def add_sample(self, sample: 'ConfidenceSample'):
        self.history.append(sample)
        self.uncertainty_window.append(sample.uncertainty)
        self.total_responses += 1
        self.last_confidence = sample.confidence
        self.last_uncertainty = sample.uncertainty
        if sample.confidence < CONFIDENCE_THRESHOLD:
            self.low_confidence_count += 1
    
    @property
    def avg_uncertainty(self) -> float:
        if not self.uncertainty_window:
            return 0.0
        return sum(self.uncertainty_window) / len(self.uncertainty_window)
    
    @property
    def avg_confidence(self) -> float:
        if not self.history:
            return 1.0
        return sum(s.confidence for s in self.history) / len(self.history)
    
    @property
    def is_uncertain(self) -> bool:
        return self.avg_uncertainty > UNCERTAINTY_THRESHOLD

# Constantes
CONFIDENCE_THRESHOLD = 0.65      # Abaixo disso = incerto
HIGH_CONFIDENCE = 0.85           # Acima = confiante
UNCERTAINTY_WINDOW = 5           # Tokens para média móvel
UNCERTAINTY_THRESHOLD = 0.4      # Score de incerteza alto
MAX_HISTORY = 1000               # Histórico de confiança
UNCERTAINTY_THRESHOLD = 0.4      # Score de incerteza alto
MAX_HISTORY = 1000               # Histórico de confiança
CONFIDENCE_THRESHOLD = 0.65      # Abaixo disso = incerto
HIGH_CONFIDENCE = 0.85           # Acima = confiante
UNCERTAINTY_WINDOW = 5           # Tokens para média móvel

# ── Metacognition Engine ───────────────────────────────────────────
class MetacognitionEngine:
    """
    Motor de metacognição para JARVIS.
    Monitora confiança, detecta incerteza, auto-avalia antes de falar,
    detecta erros e auto-corrige.
    """
    
    def __init__(self, base_url: str = "http://127.0.0.1:8092"):
        self.base_url = base_url
        self.state = MetacognitionState()
        self.lock = threading.RLock()
        
        # Callbacks para integração com sistema existente
        self.on_low_confidence: Optional[Callable] = None
        self.on_self_correction: Optional[Callable] = None
        self.on_uncertainty_detected: Optional[Callable] = None
        
        # Cache de logprobs do LLM (para evitar chamadas extras)
        self._logprob_cache: Dict[str, float] = {}
        self._logprob_lock = threading.Lock()
        
        # Estatísticas
        self.stats = {
            'total_responses': 0,
            'low_confidence': 0,
            'self_corrections': 0,
            'aborted': 0,
            'pre_speech_checks': 0,
            'uncertainty_events': 0,
        }
    
    # ── Confidence Estimation ──────────────────────────────────────
    
    def estimate_confidence_llm(self, text: str, base_url: str = None) -> float:
        """
        Estima confiança usando logprobs do LLM.
        Retorna confiança 0.0-1.0 baseado em logprobs do modelo.
        """
        # Por enquanto usa heurística - pode ser expandido para usar logprobs reais
        return self._heuristic_confidence(text)
    
    def _heuristic_confidence(self, text: str) -> float:
        """Estimativa heurística quando logprobs não disponíveis."""
        text_lower = text.lower().strip()
        
        # Sinais de baixa confiança
        uncertainty_markers = [
            'não sei', 'não sei dizer', 'não tenho certeza', 'talvez',
            'tal vez', 'acho que', 'creio que', 'imagino que', 'pode ser',
            'não tenho certeza', 'não sei', 'não sei dizer', 'não tenho certeza',
            'não tenho como saber', 'não faço ideia', 'não faço ideia'
        ]
        
        # Sinais de alta confiança
        confidence_markers = [
            'é exatamente', 'com certeza', 'com toda certeza',
            'definitivamente', 'absolutamente', 'sem dúvida',
            'com certeza', 'tenho certeza', 'é fato'
        ]
        
        text_lower = text.lower()
        
        # Verifica marcadores
        uncertainty_score = sum(1 for m in uncertainty_markers if m in text_lower)
        confidence_score = sum(1 for m in confidence_markers if m in text_lower)
        
        # Heurísticas adicionais
        # Respostas muito curtas = menos confiante (pode ser evasiva)
        word_count = len(text.split())
        if word_count < 3:
            return 0.3
        
        # Hedging language
        hedge_count = sum(1 for h in ['tipo', 'mais ou menos', 'mais ou menos', 
                                       'meio que', 'assim', 'mais ou menos', 'sei lá'] 
                          if h in text.lower())
        
        # Cálculo final
        base = 0.7
        base -= uncertainty_score * 0.15
        base += confidence_score * 0.1
        base -= min(uncertainty_score * 0.1, 0.3)
        
        return max(0.1, min(1.0, base))
    
    def estimate_confidence(self, text: str, logprobs: List[float] = None) -> float:
        """Estima confiança de uma resposta."""
        with self.lock:
            conf = self._heuristic_confidence(text)
            return conf
    
    def _heuristic_confidence(self, text: str) -> float:
        """Estimativa heurística quando logprobs não disponíveis."""
        text_lower = text.lower().strip()
        
        # Sinais de baixa confiança
        uncertainty_markers = [
            'não sei', 'não sei dizer', 'não tenho certeza', 'talvez',
            'tal vez', 'acho que', 'creio que', 'imagino que', 'pode ser',
            'não tenho certeza', 'não sei', 'não sei dizer', 'não tenho certeza',
            'não tenho como saber', 'não faço ideia', 'não faço ideia'
        ]
        
        # Sinais de alta confiança
        confidence_markers = [
            'é exatamente', 'com certeza', 'com toda certeza',
            'definitivamente', 'absolutamente', 'sem dúvida',
            'com certeza', 'tenho certeza', 'é fato'
        ]
        
        text_lower = text.lower()
        
        # Verifica marcadores
        uncertainty_score = sum(1 for m in uncertainty_markers if m in text_lower)
        confidence_score = sum(1 for m in confidence_markers if m in text_lower)
        
        # Loss heuristics
        word_count = len(text.split())
        if word_count < 3:
            return 0.3
        
        # Hedging language
        hedge_count = sum(1 for h in ['tipo', 'mais ou menos', 'mais ou menos', 
                                       'meio que', 'assim', 'mais ou menos', 'sei lá'] 
                          if h in text_lower)
        
        # Cálculo final
        base = 0.7
        base -= uncertainty_score * 0.15
        base += confidence_score * 0.1
        base -= min(uncertainty_score * 0.1, 0.3)
        
        return max(0.1, min(1.0, base))

    def estimate_confidence(self, text: str, logprobs: List[float] = None) -> float:
        """Estima confiança de uma resposta."""
        with self.lock:
            conf = self._heuristic_confidence(text)
            return conf
    
    # ── Self-Evaluation Pré-Fala ───────────────────────────────────
    
    def pre_speech_check(self, text: str, context: Dict = None) -> Tuple[bool, float, str]:
        """
        Auto-avaliação ANTES de falar.
        Retorna: (should_speak, confidence, reason)
        """
        with self.lock:
            self.stats['pre_speech_checks'] += 1
            
            # 1. Estima confiança
            confidence = self.estimate_confidence(text)
            
            # 2. Verifica incerteza explícita
            uncertainty = 1.0 - self.estimate_confidence(text)
            
            # 2. Verifica marcadores de incerteza
            uncertainty_score = self._uncertainty_score(text)
            
            # 3. Verifica se admite não saber
            admits_uncertainty = any(p in text.lower() for p in 
                ['não sei', 'não sei dizer', 'não tenho certeza', 'não tenho como saber',
                 'não tenho como saber', 'não faço ideia', 'não faço ideia'])
            
            # 3. Verifica hedging excessivo
            hedging = sum(1 for h in ['talvez', 'tal vez', 'acho que', 'creio que', 'imagino que', 
                                      'pode ser', 'mais ou menos', 'mais ou menos', 'sei lá'] 
                          if h in text.lower())
            
            # Decisão
            should_speak = True
            reason = "ok"
            
            if uncertainty > 0.7:
                should_speak = False
                reason = f"Alta incerteza ({uncertainty:.2f})"
            elif self.estimate_confidence(text) < CONFIDENCE_THRESHOLD:
                should_speak = False
                reason = f"Baixa confiança ({self.estimate_confidence(text):.2f})"
            elif uncertainty_score > 0.5 and not admits_uncertainty:
                should_speak = False
                reason = f"Incerteza alta sem admitir ({uncertainty_score:.2f})"
            
            # Atualiza stats
            self.stats['pre_speech_checks'] += 1
            if not should_speak:
                self.stats['aborted'] += 1
            
            return should_speak, self.estimate_confidence(text), f"uncertainty={uncertainty:.2f}"
    
    def _uncertainty_score(self, text: str) -> float:
        """Score de incerteza 0-1 baseado em heurísticas."""
        score = 0.0
        text_lower = text.lower()
        
        # Marcadores de incerteza
        for m in ['não sei', 'não sei dizer', 'não tenho certeza', 'talvez', 
                  'tal vez', 'acho que', 'creio que', 'imagino que', 'pode ser',
                  'não tenho certeza', 'não sei', 'não sei dizer', 'não tenho certeza',
                  'não tenho como saber', 'não faço ideia', 'não faço ideia']:
            if m in text_lower:
                score += 0.2
        
        # Hedging
        for h in ['talvez', 'tal vez', 'acho que', 'creio que', 'imagino que', 
                  'pode ser', 'na verdade', 'bom', 'bem', 'tipo assim', 'mais ou menos',
                  'tipo assim', 'assim', 'mais ou menos', 'sei lá']:
            if h in text_lower:
                score += 0.1
        
        # Perguntas retóricas = incerteza
        if text.strip().endswith('?'):
            score += 0.1
        
        # Respostas muito curtas = evasivas
        if len(text.split()) < 4:
            score += 0.3
        
        return min(1.0, score)
    
    # ── Self-Evaluation (Pós-Fala) ─────────────────────────────────
    
    def evaluate_response(self, text: str, context: Dict = None) -> Dict:
        """Auto-avaliação PÓS-fala: confiança, incerteza, risco de
        alucinação, necessidade de auto-correção."""
        conf = self.estimate_confidence(text)
        unc = 1.0 - conf
        eval_result = {
            'confidence': conf,
            'uncertainty': unc,
            'admits_uncertainty': any(m in text.lower() for m in (
                'não sei', 'não sei dizer', 'não tenho certeza')),
            'hallucination_risk': unc if unc > 0.6 else 0.0,
            'self_correction_needed': False,
            'reason': '',
        }
        # auto-correção confessada pelo próprio modelo
        if any(m in text.lower() for m in ('errei', 'me corrijo', 'na verdade, não')):
            eval_result['self_correction'] = True
            eval_result['self_correction_needed'] = True
            eval_result['reason'] = 'auto-correção confessada'
            self.stats['self_corrections'] += 1
        # tool esperada mas não chamada
        if context and context.get('expected_tool'):
            eval_result['self_correction_needed'] = True
            eval_result['reason'] = 'tool esperada não chamada'
        # registra
        self.state.add_sample(ConfidenceSample(
            timestamp=time.time(), text=text[:200], confidence=conf,
            uncertainty=unc, source='post_speech_eval'))
        return eval_result

    def _uncertainty_score(self, text: str) -> float:
        """Score de incerteza 0-1 baseado em heurísticas."""
        score = 0.0
        text_lower = text.lower()
        
        # Marcadores de incerteza
        for m in ['não sei', 'não sei dizer', 'não tenho certeza', 'talvez', 
                  'tal vez', 'acho que', 'creio que', 'imagino que', 'pode ser',
                  'não tenho certeza', 'não sei', 'não sei dizer', 'não tenho certeza',
                  'não tenho como saber', 'não faço ideia', 'não faço ideia']:
            if m in text_lower:
                score += 0.2
        
        # Hedging
        for h in ['talvez', 'tal vez', 'acho que', 'creio que', 'imagino que', 'pode ser',
                  'na verdade', 'bom', 'bem', 'tipo assim', 'assim', 'assim', 'mais ou menos', 
                  'sei lá', 'tipo assim', 'assim', 'assim', 'assim']:
            if h in text_lower:
                score += 0.1
        
        # Perguntas retóricas = incerteza
        if text.strip().endswith('?'):
            score += 0.1
        
        # Respostas muito curtas = evasivas
        if len(text.split()) < 4:
            score += 0.3
        
        return min(1.0, score)
    
    # ── Uncertainty Detection ──────────────────────────────────────
    
    # ── P2.8: Multi-hop reasoning (24/10, roadmap inteligência) ──────
    # Pergunta complexa tem ≥2 âncoras de aspecto ("o que eu gosto E onde
    # eu moro?") — uma única query de embedding DILUI os dois tópicos e
    # falha nos dois (provado: 'onde eu moro' só achava com sinônimo).
    # Decomposição heurística → múltiplos recalls → merge dedup.
    QUESTION_ANCHORS = re.compile(
        r"\b(mor[oa]|gosto|nome|trabalho|aniversário|com[ée]r|cidade|"
        r"quando|onde|quem|qual|quanto|por que|como|prefere|gosta)\b", re.I)
    SPLIT_RE = re.compile(r"\s+(?:e|ou)\s+|,\s*", re.I)

    def decompose_question(self, text: str) -> list:
        """P2.8: decompõe pergunta complexa em sub-perguntas (máx 3).
        Retorna [text] (lista unitária) se simples — nunca lista vazia
        para input não-vazio. Só decompõe quando CADA parte carrega sua
        própria âncora (evita quebrar frases com 'e' incidental)."""
        if not text:
            return []
        if len(text.split()) < 4:
            return [text]
        parts = [p.strip(" .?!") for p in self.SPLIT_RE.split(text)
                 if p.strip(" .?!")]
        anchored = [p for p in parts if self.QUESTION_ANCHORS.search(p)]
        if 2 <= len(anchored) <= 4 and len(anchored) < len(parts) + 1:
            return anchored[:3]
        return [text]

    def detect_uncertainty(self, text: str) -> Tuple[bool, float, str]:
        """Detecta incerteza: score > UNCERTAINTY_THRESHOLD = incerto."""
        score = self._uncertainty_score(text)
        if score > UNCERTAINTY_THRESHOLD:
            self.stats['uncertainty_events'] += 1
            return True, score, f"Incerteza: {score:.2f}"
        return False, score, "OK"
    
    # ── Reação Cognitiva (auto-correção + curiosidade ativa) ───────
    
    # padrões de afirmação factual (número/data/nome próprio) — onde
    # incerteza vira RETRATA (o modelo se corrige em voz alta)
    FACTUAL = re.compile(
        r"\b(\d{1,2}[h:]\d{2}|\d{1,2}/\d{1,2}|\d{4}|real|dólar|euro|"
        r"temperatura|graus|cap[íi]tal|custo|R\$|pre[çc]o)\b", re.I)
    # padrões de pergunta de dado (onde curiosidade ativa dispara busca)
    DATA_ASK = re.compile(
        r"(que horas|que dia|que ano|qual (a )?(data|hora|cota[çc][ãa]o|"
        r"pre[çc]o|custo|temperatura|clima|capital)|quanto (custa|est[áa]|"
        r"vale|t[áa])|quem (é|e) |quando |onde fica|not[íi]cia)", re.I)
    
    def react(self, text: str, heard: str = "") -> Dict:
        """Decide a REAÇÃO cognitiva à própria resposta falada.
        Retorna {action, reason, say}:
        - RETRACT: afirmação factual incerta → retrata em voz alta
        - ASK:     não sabe de algo perguntável → pergunta ao dono
        - SEARCH:  pergunta de dado externo → busca (curiosidade ativa)
        - NONE:    confiante → nada
        """
        unc, score, _ = self.detect_uncertainty(text)
        has_fact = bool(self.FACTUAL.search(text))
        heard_asks = bool(self.DATA_ASK.search(heard or ""))
        admits = any(m in text.lower() for m in (
            'não sei', 'não sei dizer', 'não tenho certeza', 'não faço ideia'))
        
        # 1. curiousidade ativa: o dono perguntou um dado e eu não sei
        #    → não invento: digo que vou buscar (ou pergunto de volta)
        if heard_asks and admits:
            return {'action': 'SEARCH',
                    'reason': 'não sei o dado pedido — vou buscar',
                    'say': 'Não sei dizer de cabeça. Deixa eu verificar pra você.'}
        # 2. retração: afirmei um fato com incerteza alta
        if has_fact and unc and score > 0.7:
            return {'action': 'RETRACT',
                    'reason': 'afirmação factual incerta',
                    'say': 'Hmm, deixa eu confirmar isso antes — não quero te falar errado.'}
        # 3. perguntável e incerto → pergunta ao dono
        if unc and score > 0.7 and heard_asks:
            return {'action': 'ASK',
                    'reason': 'incerto sobre o que foi perguntado',
                    'say': 'Não tenho certeza. Você sabe me dizer, ou quer que eu pesquise?'}
        return {'action': 'NONE', 'reason': 'confiante', 'say': ''}

    # ── Self-Correction (Online) ───────────────────────────────────
    
    def attempt_self_correction(self, original_text: str, corrected_text: str, 
                                 reason: str) -> bool:
        """
        Tenta auto-correção online.
        Retorna True se correção foi aplicada.
        """
        if not original_text or not corrected_text:
            return False
        
        # Log da correção
        self.stats['self_corrections'] += 1
        
        if self.on_self_correction:
            try:
                self.on_self_correction(original_text, corrected_text, reason)
            except Exception:
                pass
        
        # Registra no estado
        with self.lock:
            self.state.self_corrections += 1
        
        return True
    
    def detect_and_correct(self, text: str) -> Tuple[str, bool]:
        """
        Detecta e corrige problemas na resposta.
        Retorna (texto_corrigido, foi_corrigido).
        """
        # Verifica alucinação de dados (números inventados)
        # Verifica contradições internas
        # Verifica confissão de incerteza sem admitir
        
        # Por enquanto, retorna original
        return text, False
    
    # ── Integration Hooks ──────────────────────────────────────────
    
    def set_callbacks(self, on_low_confidence=None, on_self_correction=None, 
                      on_uncertainty=None):
        self.on_low_confidence = on_low_confidence
        self.on_self_correction = on_self_correction
        self.on_uncertainty_detected = on_uncertainty
    
    # ── Stats & Monitoring ────────────────────────────────────────
    
    def get_stats(self) -> Dict:
        with self.lock:
            return {
                **self.stats,
                'avg_confidence': self.state.avg_confidence,
                'avg_uncertainty': self.state.avg_uncertainty,
                'is_uncertain': self.state.is_uncertain,
            }
    
    def get_state_summary(self) -> Dict:
        with self.lock:
            return {
                'total_responses': self.state.total_responses,
                'low_confidence_rate': self.state.low_confidence_count / max(1, self.state.total_responses),
                'self_corrections': self.state.self_corrections,
                'aborted_responses': self.state.aborted_responses,
                'avg_confidence': self.state.avg_confidence,
                'avg_uncertainty': self.state.avg_uncertainty,
                'is_currently_uncertain': self.state.is_uncertain,
            }

# ── Global Instance ───────────────────────────────────────────────
_metacognition_instance: Optional[MetacognitionEngine] = None
_metacognition_lock = threading.Lock()

def get_metacognition(base_url: str = "http://127.0.0.1:8092") -> MetacognitionEngine:
    """Singleton para instância global de metacognição."""
    global _metacognition_instance
    with _metacognition_lock:
        if _metacognition_instance is None:
            _metacognition_instance = MetacognitionEngine()
        return _metacognition_instance


# ── Helpers para integração com duplex-voice.py ──────────────────

def pre_speech_check(text: str, context: Dict = None) -> Tuple[bool, float, str]:
    """Verifica se deve falar. Retorna (should_speak, confidence, reason)."""
    engine = get_metacognition()
    return engine.pre_speech_check(text)

def evaluate_response(text: str, context: Dict = None) -> Dict:
    """Avalia resposta após fala."""
    engine = get_metacognition()
    return engine.evaluate_response(text)

def detect_uncertainty(text: str) -> Tuple[bool, float, str]:
    engine = get_metacognition()
    return engine.detect_uncertainty(text)

def estimate_confidence(text: str) -> float:
    engine = get_metacognition()
    return engine.estimate_confidence(text)

def detect_uncertainty(text: str) -> Tuple[bool, float, str]:
    engine = get_metacognition()
    return engine.detect_uncertainty(text)

def self_correct(original: str, corrected: str, reason: str) -> bool:
    engine = get_metacognition()
    return engine.attempt_self_correction(original, corrected, reason)

def get_metacognition_stats() -> Dict:
    engine = get_metacognition()
    return engine.get_stats()

def get_metacognition_state() -> Dict:
    engine = get_metacognition()
    return engine.get_state_summary()