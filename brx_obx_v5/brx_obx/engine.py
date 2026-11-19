"""Deterministic, point-in-time underlying bias calculations.

No SMA, EMA, MACD, VWAP, ML, or cross-timeframe entry gate. No provider IO.
Feature adapters must ensure every input is timestamped at or before evaluation time.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional, Sequence
from math import isfinite

WEIGHTS: dict[str, dict[str, int]] = {
    'monthly': {'structure':25,'volume':10,'momentum':25,'breakout':15,'relative_strength':10,'breadth':10,'futures':5},
    'weekly': {'structure':25,'volume':15,'momentum':25,'breakout':15,'relative_strength':10,'breadth':5,'futures':5},
    'daily': {'structure':20,'volume':15,'momentum':10,'breakout':35,'relative_strength':10,'breadth':5,'futures':5},
    '1m': {'structure':30,'volume':15,'breakout':20,'impulse':15,'futures':10,'breadth':10},
    '3m': {'structure':30,'volume':15,'breakout':20,'impulse':15,'futures':10,'breadth':10},
    '5m': {'structure':30,'volume':15,'breakout':20,'impulse':15,'futures':10,'breadth':10},
    '15m': {'structure':30,'volume':15,'breakout':20,'impulse':15,'futures':10,'breadth':10},
}
assert all(sum(x.values()) == 100 for x in WEIGHTS.values())

@dataclass(frozen=True)
class Evidence:
    sign: Optional[int]           # +1 bullish, 0 neutral, -1 bearish, None unavailable
    observed_at: datetime         # when the evidence became knowable (not pivot origin)
    reason: str = ''
    def __post_init__(self):
        if self.sign not in (-1, 0, 1, None):
            raise ValueError('sign must be -1, 0, 1 or None')
        if self.observed_at.tzinfo is None:
            raise ValueError('observed_at must be timezone aware')

@dataclass(frozen=True)
class BiasResult:
    symbol: str
    timeframe: str
    raw_bias: str
    confirmed_bias: str
    net_score: int
    coverage: float
    strength: str
    status: str
    reasons: tuple[str, ...]
    evaluation_time: datetime

class BiasEngine:
    """Maintains independent confirmed states by (symbol,timeframe).

    Closed evaluations alone update confirmed state. An opposing flip requires
    two successive closed evaluations; provisional updates never increment it.
    """
    def __init__(self):
        self._state: dict[tuple[str,str],str] = {}
        self._pending: dict[tuple[str,str],tuple[str,int]] = {}
        self._last_closed: dict[tuple[str,str],datetime] = {}

    def evaluate(self, symbol: str, timeframe: str, evidence: Mapping[str,Evidence],
                 as_of: datetime, *, closed: bool) -> BiasResult:
        if as_of.tzinfo is None: raise ValueError('as_of must be timezone aware')
        if timeframe not in WEIGHTS: raise ValueError('unknown timeframe')
        if not symbol: raise ValueError('empty symbol')
        unknown = set(evidence) - set(WEIGHTS[timeframe])
        if unknown: raise ValueError(f'unknown features: {sorted(unknown)}')
        key = (symbol, timeframe)
        if closed and key in self._last_closed and as_of <= self._last_closed[key]:
            raise ValueError('closed evaluations must have strictly increasing timestamps')
        score = 0
        covered = 0
        reasons = []
        for name, weight in WEIGHTS[timeframe].items():
            item = evidence.get(name)
            if item is None or item.sign is None:
                reasons.append(f'{name}:UNAVAILABLE')
                continue
            if item.observed_at > as_of:
                raise ValueError(f'lookahead evidence: {name}')
            covered += weight
            score += weight*item.sign
            reasons.append(f'{name}:{item.sign:+d}:{item.reason}')
        coverage = covered / 100
        sufficient = coverage >= 0.75 and evidence.get('structure') is not None and evidence['structure'].sign is not None
        raw = ('CALL' if score>=35 else 'PUT' if score<=-35 else 'NEUTRAL') if sufficient else 'INSUFFICIENT_DATA'
        prior = self._state.get(key,'NEUTRAL')
        confirmed_bias = prior
        if closed:
            self._last_closed[key] = as_of
            if sufficient:
                if raw in ('CALL','PUT'):
                    if prior in ('CALL','PUT') and raw != prior:
                        direction,n = self._pending.get(key,(raw,0))
                        n = n+1 if direction == raw else 1
                        self._pending[key] = (raw,n)
                        if n>=2:
                            confirmed_bias = raw
                            self._pending.pop(key,None)
                    elif prior=='NEUTRAL':
                        confirmed_bias = raw
                        self._pending.pop(key,None)
                    else:
                        self._pending.pop(key,None)
                elif abs(score)<20:
                    confirmed_bias='NEUTRAL'
                    self._pending.pop(key,None)
                else:
                    self._pending.pop(key,None)
                self._state[key] = confirmed_bias
        return BiasResult(symbol,timeframe,raw,confirmed_bias,score,coverage,
                          'STRONG' if abs(score)>=60 else 'MODERATE' if abs(score)>=35 else 'UNRESOLVED',
                          ('INSUFFICIENT_DATA' if not sufficient else 'CONFIRMED' if closed else 'PROVISIONAL'),
                          tuple(reasons),as_of)

@dataclass(frozen=True)
class ReversalResult:
    state: str
    score: int
    target_bias: Optional[str]

def evaluate_reversal(confirmed_bias: str, indicators: Mapping[str,bool]) -> ReversalResult:
    """Separate warnings: never modifies BiasEngine state or opens trades."""
    weights={'failed_breakout':25,'relative_strength_breakdown':20,
             'breadth_divergence':20,'futures_divergence':10,'momentum_exhaustion':25}
    if confirmed_bias not in ('CALL','PUT'):
        return ReversalResult('TREND_CONTINUATION',0,None)
    unknown=set(indicators)-set(weights)
    if unknown: raise ValueError(f'unknown reversal keys: {sorted(unknown)}')
    score=sum(weight for name,weight in weights.items() if indicators.get(name,False))
    price_evidence = bool(indicators.get('failed_breakout'))
    other_evidence = any(indicators.get(k,False) for k in ('relative_strength_breakdown','breadth_divergence','futures_divergence','momentum_exhaustion'))
    state = ('REVERSAL_CONFIRMED' if score>=70 and price_evidence and other_evidence
             else 'REVERSAL_WATCH' if score>=40 else 'TREND_CONTINUATION')
    return ReversalResult(state,score,('PUT' if confirmed_bias=='CALL' else 'CALL') if state!='TREND_CONTINUATION' else None)

@dataclass(frozen=True)
class Bar:
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    def __post_init__(self):
        if self.end.tzinfo is None: raise ValueError('bar end needs timezone')
        if not all(isfinite(z) for z in (self.open,self.high,self.low,self.close,self.volume)):
            raise ValueError('nonfinite OHLCV')
        if self.high < max(self.open,self.close,self.low) or self.low > min(self.open,self.close,self.high) or self.volume < 0:
            raise ValueError('invalid OHLCV')

def confirmed_pivots(closed_bars: Sequence[Bar], left: int, right: int):
    """Returns (kind, pivot_index, known_at), excluding any unconfirmed right edge."""
    if left<1 or right<1: raise ValueError('left and right must be positive')
    if any(a.end >= b.end for a,b in zip(closed_bars,closed_bars[1:])):
        raise ValueError('bars must be strictly chronological')
    result=[]
    for i in range(left, len(closed_bars)-right):
        before=closed_bars[i-left:i]
        after=closed_bars[i+1:i+right+1]
        bar=closed_bars[i]
        if all(bar.high>x.high for x in before) and all(bar.high>=x.high for x in after):
            result.append(('HIGH',i,closed_bars[i+right].end))
        if all(bar.low<x.low for x in before) and all(bar.low<=x.low for x in after):
            result.append(('LOW',i,closed_bars[i+right].end))
    return result

def volume_percentile(current: float, matching_prior_slots: Sequence[float]):
    """Empirical percentile using only prior same-session clock slots, no smoothing."""
    if current < 0 or not isfinite(current): raise ValueError('invalid volume')
    if len(matching_prior_slots) < 10: return None
    if any(x<0 or not isfinite(x) for x in matching_prior_slots): raise ValueError('bad historical volumes')
    return sum(x<=current for x in matching_prior_slots)/len(matching_prior_slots)
