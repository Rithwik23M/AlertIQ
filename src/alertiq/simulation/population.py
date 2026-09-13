"""
Account population generator.

Generates a fixed population of accounts whose risk categories are drawn
from PopulationMix proportions.  Each account gets a seeded sub-generator
derived from the master seed so that:

  * Adding more accounts never changes existing account properties.
  * Account-level properties are reproducible given (master_seed, account_idx).

The population is generated once at simulation start and held in memory.
Active-ML accounts have a typology type assigned during population generation.
"""

from __future__ import annotations

import datetime
from typing import Sequence

import numpy as np

from .config import SimulationConfig
from .entities import (
    Account,
    AccountRiskCategory,
    AccountType,
    JurisdictionRisk,
    TypologyType,
    new_id,
)

# ---------------------------------------------------------- #
# Constants                                                   #
# ---------------------------------------------------------- #

# Probability that an account has a PEP connection, by risk tier
_PEP_PROB: dict[AccountRiskCategory, float] = {
    AccountRiskCategory.LOW_RISK: 0.005,
    AccountRiskCategory.MEDIUM_RISK: 0.02,
    AccountRiskCategory.HIGH_RISK: 0.08,
    AccountRiskCategory.ACTIVE_ML: 0.15,
}

# Probability of adverse media flag, by risk tier
_ADVERSE_MEDIA_PROB: dict[AccountRiskCategory, float] = {
    AccountRiskCategory.LOW_RISK: 0.002,
    AccountRiskCategory.MEDIUM_RISK: 0.01,
    AccountRiskCategory.HIGH_RISK: 0.05,
    AccountRiskCategory.ACTIVE_ML: 0.12,
}

# Distribution of AccountType per AccountRiskCategory (probabilities, sum=1)
_ACCOUNT_TYPE_PROBS: dict[AccountRiskCategory, dict[AccountType, float]] = {
    AccountRiskCategory.LOW_RISK: {
        AccountType.RETAIL: 0.70,
        AccountType.SME: 0.20,
        AccountType.CORPORATE: 0.08,
        AccountType.SHELL: 0.00,
        AccountType.CASH_INTENSIVE: 0.01,
        AccountType.PROFESSIONAL: 0.01,
    },
    AccountRiskCategory.MEDIUM_RISK: {
        AccountType.RETAIL: 0.40,
        AccountType.SME: 0.30,
        AccountType.CORPORATE: 0.15,
        AccountType.SHELL: 0.05,
        AccountType.CASH_INTENSIVE: 0.05,
        AccountType.PROFESSIONAL: 0.05,
    },
    AccountRiskCategory.HIGH_RISK: {
        AccountType.RETAIL: 0.20,
        AccountType.SME: 0.25,
        AccountType.CORPORATE: 0.20,
        AccountType.SHELL: 0.15,
        AccountType.CASH_INTENSIVE: 0.12,
        AccountType.PROFESSIONAL: 0.08,
    },
    AccountRiskCategory.ACTIVE_ML: {
        AccountType.RETAIL: 0.10,
        AccountType.SME: 0.15,
        AccountType.CORPORATE: 0.20,
        AccountType.SHELL: 0.30,
        AccountType.CASH_INTENSIVE: 0.15,
        AccountType.PROFESSIONAL: 0.10,
    },
}

# Jurisdiction risk distribution per account risk tier
_JURISDICTION_PROBS: dict[AccountRiskCategory, dict[JurisdictionRisk, float]] = {
    AccountRiskCategory.LOW_RISK: {
        JurisdictionRisk.LOW: 0.85,
        JurisdictionRisk.MEDIUM: 0.13,
        JurisdictionRisk.HIGH: 0.02,
        JurisdictionRisk.VERY_HIGH: 0.00,
    },
    AccountRiskCategory.MEDIUM_RISK: {
        JurisdictionRisk.LOW: 0.60,
        JurisdictionRisk.MEDIUM: 0.30,
        JurisdictionRisk.HIGH: 0.08,
        JurisdictionRisk.VERY_HIGH: 0.02,
    },
    AccountRiskCategory.HIGH_RISK: {
        JurisdictionRisk.LOW: 0.30,
        JurisdictionRisk.MEDIUM: 0.35,
        JurisdictionRisk.HIGH: 0.25,
        JurisdictionRisk.VERY_HIGH: 0.10,
    },
    AccountRiskCategory.ACTIVE_ML: {
        JurisdictionRisk.LOW: 0.15,
        JurisdictionRisk.MEDIUM: 0.30,
        JurisdictionRisk.HIGH: 0.35,
        JurisdictionRisk.VERY_HIGH: 0.20,
    },
}

# Declared annual revenue (EUR) log-normal parameters per account type
_REVENUE_LOG_PARAMS: dict[AccountType, tuple[float, float]] = {
    AccountType.RETAIL: (9.5, 0.8),          # ~€13k median
    AccountType.SME: (12.0, 0.9),             # ~€162k median
    AccountType.CORPORATE: (14.5, 1.0),       # ~€2M median
    AccountType.SHELL: (13.0, 1.5),           # ~€442k median, high variance
    AccountType.CASH_INTENSIVE: (11.5, 0.7),  # ~€98k median
    AccountType.PROFESSIONAL: (12.5, 0.7),    # ~€268k median
}

# Typology weights for assigning to ACTIVE_ML accounts
_TYPOLOGY_ASSIGNMENT_PROBS: dict[TypologyType, float] = {
    TypologyType.STRUCTURING: 0.25,
    TypologyType.SHELL_COMPANY: 0.18,
    TypologyType.REAL_ESTATE: 0.12,
    TypologyType.TRADE_BASED: 0.10,
    TypologyType.CASH_INTENSIVE: 0.12,
    TypologyType.PROFESSIONAL_ML: 0.08,
    TypologyType.VIRTUAL_ASSETS: 0.08,
    TypologyType.CROSS_BORDER: 0.07,
}

# High-risk industry flag probability
_HIGH_RISK_INDUSTRY_PROBS: dict[AccountType, float] = {
    AccountType.RETAIL: 0.02,
    AccountType.SME: 0.08,
    AccountType.CORPORATE: 0.06,
    AccountType.SHELL: 0.40,
    AccountType.CASH_INTENSIVE: 0.80,
    AccountType.PROFESSIONAL: 0.10,
}


def _choice(rng: np.random.Generator, options: Sequence, probs: Sequence[float]):
    """Weighted random choice from options."""
    return options[rng.choice(len(options), p=list(probs))]


def _account_type_for_risk(
    rng: np.random.Generator,
    risk: AccountRiskCategory,
) -> AccountType:
    probs_dict = _ACCOUNT_TYPE_PROBS[risk]
    types = list(probs_dict.keys())
    probs = list(probs_dict.values())
    idx = rng.choice(len(types), p=probs)
    return types[idx]


def _jurisdiction_for_risk(
    rng: np.random.Generator,
    risk: AccountRiskCategory,
) -> JurisdictionRisk:
    probs_dict = _JURISDICTION_PROBS[risk]
    tiers = list(probs_dict.keys())
    probs = list(probs_dict.values())
    idx = rng.choice(len(tiers), p=probs)
    return tiers[idx]


def _typology_assignment(rng: np.random.Generator) -> TypologyType:
    typologies = list(_TYPOLOGY_ASSIGNMENT_PROBS.keys())
    probs = list(_TYPOLOGY_ASSIGNMENT_PROBS.values())
    idx = rng.choice(len(typologies), p=probs)
    return typologies[idx]


def _onboard_date(rng: np.random.Generator, sim_start: datetime.date) -> datetime.date:
    """Account onboarded 0–10 years before sim start."""
    days_back = int(rng.integers(0, 365 * 10))
    return sim_start - datetime.timedelta(days=days_back)


# Probability that a LOW/MEDIUM_RISK account has been dormant (no transactions
# for 90–200 days before the simulation start).  When True, last_txn_date is
# pre-set so the Dormant Account rule (R05) can fire on the first window.
_DORMANT_PROB: dict[AccountRiskCategory, float] = {
    AccountRiskCategory.LOW_RISK: 0.07,
    AccountRiskCategory.MEDIUM_RISK: 0.04,
    AccountRiskCategory.HIGH_RISK: 0.02,
    AccountRiskCategory.ACTIVE_ML: 0.00,  # ML accounts are always active
}


def generate_account_population(config: SimulationConfig) -> list[Account]:
    """Generate the full account population from config.

    Args:
        config: Frozen SimulationConfig instance.

    Returns:
        List of Account objects in deterministic order.

    The master RNG is seeded from config.seed.  Each account uses a
    child generator seeded with (master_seed, account_index) so that
    individual account properties are stable even if n_accounts changes.
    """
    master_rng = np.random.default_rng(config.seed)
    sim_start = datetime.date.fromisoformat(config.start_date)

    mix = config.population_mix
    n = config.n_accounts

    # Determine exact counts per risk category (floor + distribute remainder)
    counts = {
        AccountRiskCategory.LOW_RISK: int(mix.low_risk * n),
        AccountRiskCategory.MEDIUM_RISK: int(mix.medium_risk * n),
        AccountRiskCategory.HIGH_RISK: int(mix.high_risk * n),
        AccountRiskCategory.ACTIVE_ML: int(mix.active_ml * n),
    }
    remainder = n - sum(counts.values())
    # Assign remainder to the largest bucket (least distortion)
    largest = max(counts, key=lambda k: counts[k])
    counts[largest] += remainder

    assert sum(counts.values()) == n, "Population count mismatch — programming error"

    # Build flat risk category list in deterministic order
    risk_labels: list[AccountRiskCategory] = []
    for risk, count in counts.items():
        risk_labels.extend([risk] * count)

    # Shuffle with master RNG so risk categories are interleaved
    risk_arr = np.array(risk_labels, dtype=object)
    master_rng.shuffle(risk_arr)

    accounts: list[Account] = []
    for idx, risk in enumerate(risk_arr):
        # Child RNG — stable per (seed, index) pair
        child_rng = np.random.default_rng([config.seed, idx])

        account_type = _account_type_for_risk(child_rng, risk)
        jurisdiction = _jurisdiction_for_risk(child_rng, risk)

        log_mean, log_std = _REVENUE_LOG_PARAMS[account_type]
        revenue = float(child_rng.lognormal(log_mean, log_std))
        monthly_volume = revenue / 12.0 * float(child_rng.uniform(0.5, 1.5))

        pep_prob = _PEP_PROB[risk]
        adverse_prob = _ADVERSE_MEDIA_PROB[risk]
        high_risk_industry_prob = _HIGH_RISK_INDUSTRY_PROBS[account_type]

        assigned_typology: TypologyType | None = None
        if risk == AccountRiskCategory.ACTIVE_ML:
            assigned_typology = _typology_assignment(child_rng)

        onboard_date = _onboard_date(child_rng, sim_start)
        has_pep = bool(child_rng.random() < pep_prob)
        has_adverse = bool(child_rng.random() < adverse_prob)
        is_high_risk_industry = bool(child_rng.random() < high_risk_industry_prob)

        # Pre-assign dormancy for accounts that were inactive before sim start.
        # This allows R05 (Dormant Account Sudden Activity) to fire when the
        # account's first simulation transaction follows a long quiescent period.
        dormant_last_txn_date: datetime.date | None = None
        dormancy_prob = _DORMANT_PROB.get(risk, 0.0)
        if dormancy_prob > 0 and child_rng.random() < dormancy_prob:
            # Last transaction was 90–200 days before simulation start
            days_dormant = int(child_rng.integers(90, 201))
            dormant_last_txn_date = sim_start - datetime.timedelta(days=days_dormant)

        account = Account(
            account_id=f"ACC{idx:06d}",
            account_type=account_type,
            risk_category=risk,
            jurisdiction=jurisdiction,
            onboard_date=onboard_date,
            declared_annual_revenue=round(revenue, 2),
            expected_monthly_volume=round(monthly_volume, 2),
            has_pep_link=has_pep,
            has_adverse_media=has_adverse,
            is_high_risk_industry=is_high_risk_industry,
            assigned_typology=assigned_typology,
            last_txn_date=dormant_last_txn_date,  # None for normal accounts
        )
        accounts.append(account)

    return accounts
