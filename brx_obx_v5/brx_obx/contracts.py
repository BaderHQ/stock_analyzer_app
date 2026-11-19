"""Options classifier with hard quote/expiry/risk gates and externally repriced scenarios.

NEVER interpret directional bias score as probability of profit. No live execution.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Mapping, Sequence

@dataclass(frozen=True)
class ContractPolicy:
    max_quote_age_s: float = 5.0
    max_spread_fraction: float = 0.12  # (ask-bid)/ask; research-unvalidated baseline
    min_bid: float = 0.05
    atm_band: float = 0.005   # absolute relative strike distance
    enable_0dte: bool = False
    min_minutes_to_last_trade: int = 30
    round_trip_fees: float = 2.0

@dataclass(frozen=True)
class Scenario:
    name: str
    exit_bid: float               # externally repriced executable EXIT quote estimate
    minutes_ahead: int
    underlying_return: float      # assumption, not a forecast
    iv_change_points: float      # assumption, not a forecast

@dataclass(frozen=True)
class Contract:
    contract_id: str
    kind: str
    strike: float
    spot: float
    bid: float
    ask: float
    quote_time: datetime
    last_trade_time: datetime
    days_to_expiry: int
    multiplier: int = 100
    delta: float|None = None
    gamma: float|None = None
    theta: float|None = None
    vega: float|None = None
    iv: float|None = None
    open_interest: int|None = None
    volume: int|None = None
    settlement: str = 'UNKNOWN'

@dataclass(frozen=True)
class ContractDecision:
    contract_id: str
    status: str
    moneyness: str
    reason_codes: tuple[str,...]
    base_pnl: float|None = None
    adverse_pnl: float|None = None
    base_return_on_debit: float|None = None


def moneyness(c: Contract, band: float) -> str:
    if c.spot<=0 or c.strike<=0: return 'INVALID'
    if abs(c.strike-c.spot)/c.spot<=band: return 'ATM'
    intrinsic = c.spot-c.strike if c.kind=='CALL' else c.strike-c.spot
    return 'ITM' if intrinsic>0 else 'OTM'

def select_contracts(direction: str, contracts: Sequence[Contract], scenarios: Mapping[str,Mapping[str,Scenario]],
                     *, now: datetime, policy: ContractPolicy = ContractPolicy()) -> list[ContractDecision]:
    """Return eligible candidates, sorted by BASE net return; rejects have explicit reasons.

    Scenarios must be precomputed from validated option repricing / market replay;
    no synthetic accuracy or Greek-only full repricing is invented here.
    """
    if now.tzinfo is None: raise ValueError('now needs timezone')
    if direction not in ('CALL','PUT','NEUTRAL','INSUFFICIENT_DATA'):
        raise ValueError('invalid direction')
    out=[]
    for c in contracts:
        reasons=[]
        category=moneyness(c,policy.atm_band) if c.kind in ('CALL','PUT') else 'INVALID'
        if direction not in ('CALL','PUT'): reasons.append('NO_DIRECTION')
        if c.kind!=direction: reasons.append('WRONG_SIDE')
        if category=='INVALID': reasons.append('INVALID_STRIKE_OR_SPOT')
        if c.quote_time.tzinfo is None or c.last_trade_time.tzinfo is None:
            reasons.append('INVALID_TIMEZONE')
        else:
            age=(now-c.quote_time).total_seconds()
            if age<0: reasons.append('QUOTE_FROM_FUTURE')
            if age>policy.max_quote_age_s: reasons.append('STALE_NBBO')
            if now>=c.last_trade_time: reasons.append('PAST_LAST_TRADE')
            if (c.last_trade_time-now).total_seconds()<60*policy.min_minutes_to_last_trade:
                reasons.append('TOO_CLOSE_TO_CUTOFF')
        if c.days_to_expiry<0: reasons.append('EXPIRED')
        if c.days_to_expiry==0 and not policy.enable_0dte: reasons.append('ZERO_DTE_DISABLED')
        if c.days_to_expiry==0 and c.settlement=='UNKNOWN': reasons.append('UNKNOWN_ZERO_DTE_SETTLEMENT')
        prices=(c.bid,c.ask,c.strike,c.spot)
        if not all(isfinite(x) for x in prices) or c.bid<policy.min_bid or c.ask<=0 or c.ask<c.bid:
            reasons.append('INVALID_NBBO')
        elif (c.ask-c.bid)/c.ask>policy.max_spread_fraction:
            reasons.append('WIDE_SPREAD')
        if c.multiplier<=0: reasons.append('INVALID_MULTIPLIER')
        if c.delta is None or c.gamma is None or c.theta is None or c.vega is None or c.iv is None:
            reasons.append('MISSING_GREEKS')
        else:
            if not all(isfinite(x) for x in (c.delta,c.gamma,c.theta,c.vega,c.iv)) or c.iv<=0 or abs(c.delta)>1:
                reasons.append('INVALID_GREEKS')
        s=scenarios.get(c.contract_id,{})
        if 'base' not in s or 'adverse' not in s:
            reasons.append('MISSING_SCENARIOS')
        else:
            for k in ('base','adverse'):
                if s[k].exit_bid<0 or not isfinite(s[k].exit_bid) or s[k].minutes_ahead<0:
                    reasons.append('INVALID_SCENARIOS')
                if c.days_to_expiry==0 and s[k].minutes_ahead*60 > max(0,(c.last_trade_time-now).total_seconds()):
                    reasons.append('SCENARIO_BEYOND_CUTOFF')
        if reasons:
            out.append(ContractDecision(c.contract_id,'NO_TRADE',category,tuple(dict.fromkeys(reasons))))
            continue
        debit=c.ask*c.multiplier+policy.round_trip_fees
        base=(s['base'].exit_bid-c.ask)*c.multiplier-policy.round_trip_fees
        adverse=(s['adverse'].exit_bid-c.ask)*c.multiplier-policy.round_trip_fees
        if base<=0:
            out.append(ContractDecision(c.contract_id,'NO_TRADE',category,('NONPOSITIVE_BASE_CASE',),base,adverse,base/debit))
            continue
        out.append(ContractDecision(c.contract_id,'CANDIDATE',category,(),base,adverse,base/debit))
    return sorted(out,key=lambda x:(x.status!='CANDIDATE',-(x.base_return_on_debit if x.base_return_on_debit is not None else float('-inf')),x.contract_id))
