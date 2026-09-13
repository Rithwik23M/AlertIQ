"""
AlertIQ Simulation Engine — public API.

Quick-start:
    from alertiq.simulation import run_simulation, SimulationConfig

    result = run_simulation(SimulationConfig(seed=42, n_accounts=1_000))
    print(result.summary())
"""

from .config import SimulationConfig
from .entities import (
    Account,
    AccountRiskCategory,
    AccountType,
    Alert,
    AlertSeverity,
    AlertStatus,
    Channel,
    JurisdictionRisk,
    SimulationResult,
    Transaction,
    TransactionType,
    TypologyType,
)
from .runner import SimulationError, run_simulation

__all__ = [
    "SimulationConfig",
    "run_simulation",
    "SimulationError",
    "SimulationResult",
    "Account",
    "AccountRiskCategory",
    "AccountType",
    "Alert",
    "AlertSeverity",
    "AlertStatus",
    "Channel",
    "JurisdictionRisk",
    "Transaction",
    "TransactionType",
    "TypologyType",
]
