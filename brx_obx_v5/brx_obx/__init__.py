"""BRX/OBX v5: deterministic alert-only building blocks, no market-data provider assumptions."""
from .engine import BiasEngine, Evidence, evaluate_reversal, confirmed_pivots, volume_percentile
from .contracts import Contract, Scenario, ContractPolicy, select_contracts
