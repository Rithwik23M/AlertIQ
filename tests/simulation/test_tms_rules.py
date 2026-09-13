"""
Tests for TMS rule engine.

Covers: rule triggering, severity assignment, non-triggering edge cases,
        alert structure contracts, no-ground-truth guarantee.
"""

from __future__ import annotations

import datetime

import pytest

from alertiq.simulation.config import SimulationConfig
from alertiq.simulation.entities import (
    AccountRiskCategory,
    AccountType,
    AlertSeverity,
    Channel,
    Counterparty,
    JurisdictionRisk,
    Transaction,
    TransactionType,
    TypologyType,
    new_id,
)
from alertiq.simulation.tms import ALL_RULES, RULE_BY_ID, configure_thresholds
from alertiq.simulation.tms.rules import (
    CashStructuringRule,
    CrossBorderFanOutRule,
    DormantAccountRule,
    HighRiskJurisdictionRule,
    LargeCashRule,
    LayeringRule,
    OffHoursPatternRule,
    PEPHighValueRule,
    RapidFundMovementRule,
    RealEstateLargeRule,
    ShellCounterpartyRule,
    TradeInvoiceAnomalyRule,
    VelocitySpikeRule,
)
from tests.simulation.conftest import (
    make_cash_deposit,
    make_intl_wire,
)

CONFIG = SimulationConfig(seed=0)
configure_thresholds(CONFIG)


def _account(pep=False, adverse=False, high_risk=False, risk=AccountRiskCategory.MEDIUM_RISK):
    from alertiq.simulation.entities import Account
    import datetime
    return Account(
        account_id="TEST",
        account_type=AccountType.RETAIL,
        risk_category=risk,
        jurisdiction=JurisdictionRisk.LOW,
        onboard_date=datetime.date(2015, 1, 1),
        declared_annual_revenue=50_000.0,
        expected_monthly_volume=4_000.0,
        has_pep_link=pep,
        has_adverse_media=adverse,
        is_high_risk_industry=high_risk,
    )


TODAY = datetime.date(2023, 6, 15)


class TestCashStructuringRule:
    rule = CashStructuringRule()

    def test_triggers_on_3_near_threshold_deposits(self):
        account = _account()
        txns = [make_cash_deposit("TEST", 8_500.0) for _ in range(3)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 1

    def test_does_not_trigger_below_count(self):
        account = _account()
        txns = [make_cash_deposit("TEST", 8_500.0) for _ in range(2)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 0

    def test_does_not_trigger_on_large_deposits(self):
        """Deposits ≥ CTR threshold should not trigger structuring rule."""
        account = _account()
        txns = [make_cash_deposit("TEST", 12_000.0) for _ in range(5)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 0

    def test_alert_has_no_ground_truth(self):
        account = _account()
        txns = [make_cash_deposit("TEST", 8_500.0) for _ in range(3)]
        alerts = self.rule.evaluate(account, txns, txns)
        for alert in alerts:
            assert alert.true_sar is None


class TestLargeCashRule:
    rule = LargeCashRule()

    def test_triggers_on_large_deposit(self):
        account = _account()
        txns = [make_cash_deposit("TEST", 9_000.0)]  # > 8_000 threshold
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 1

    def test_critical_severity_at_3x_threshold(self):
        account = _account()
        txns = [make_cash_deposit("TEST", 25_000.0)]  # 3× 8_000
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_no_trigger_below_threshold(self):
        account = _account()
        txns = [make_cash_deposit("TEST", 7_999.0)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 0


class TestHighRiskJurisdictionRule:
    rule = HighRiskJurisdictionRule()

    def test_triggers_on_high_risk_wire(self):
        account = _account()
        txns = [make_intl_wire("TEST", 10_000.0, JurisdictionRisk.HIGH)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 1

    def test_critical_for_very_high_jurisdiction(self):
        account = _account()
        txns = [make_intl_wire("TEST", 10_000.0, JurisdictionRisk.VERY_HIGH)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_no_trigger_low_risk_jurisdiction(self):
        account = _account()
        txns = [make_intl_wire("TEST", 100_000.0, JurisdictionRisk.LOW)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 0

    def test_no_trigger_below_amount_threshold(self):
        account = _account()
        txns = [make_intl_wire("TEST", 100.0, JurisdictionRisk.HIGH)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 0


class TestDormantAccountRule:
    rule = DormantAccountRule()

    def test_triggers_on_long_gap(self):
        account = _account()
        d1 = datetime.date(2023, 1, 1)
        d2 = datetime.date(2023, 4, 15)  # 104-day gap
        old_txn = make_cash_deposit("TEST", 100.0, d1)
        new_txn = make_cash_deposit("TEST", 6_000.0, d2)
        all_txns = [old_txn, new_txn]
        alerts = self.rule.evaluate(account, [new_txn], all_txns)
        assert len(alerts) == 1

    def test_no_trigger_on_active_account(self):
        account = _account()
        # Daily activity — no dormancy gap
        txns = [
            make_cash_deposit("TEST", 200.0, TODAY - datetime.timedelta(days=i))
            for i in range(10)
        ]
        alerts = self.rule.evaluate(account, txns[-3:], txns)
        assert len(alerts) == 0

    def test_no_trigger_low_value_reactivation(self):
        account = _account()
        d1 = datetime.date(2023, 1, 1)
        d2 = datetime.date(2023, 4, 15)
        old_txn = make_cash_deposit("TEST", 100.0, d1)
        new_txn = make_cash_deposit("TEST", 50.0, d2)  # small amount
        alerts = self.rule.evaluate(account, [new_txn], [old_txn, new_txn])
        assert len(alerts) == 0


class TestVelocitySpikeRule:
    rule = VelocitySpikeRule()

    def test_triggers_on_high_count(self):
        account = _account()
        txns = [make_cash_deposit("TEST", 100.0) for _ in range(25)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 1

    def test_no_trigger_below_threshold(self):
        account = _account()
        txns = [make_cash_deposit("TEST", 100.0) for _ in range(5)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 0


class TestPEPRule:
    rule = PEPHighValueRule()

    def test_pep_triggers_on_high_value(self):
        account = _account(pep=True)
        txns = [make_cash_deposit("TEST", 5_000.0)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_non_pep_does_not_trigger(self):
        account = _account(pep=False)
        txns = [make_cash_deposit("TEST", 5_000.0)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 0

    def test_adverse_media_triggers(self):
        account = _account(adverse=True)
        txns = [make_cash_deposit("TEST", 5_000.0)]
        alerts = self.rule.evaluate(account, txns, txns)
        assert len(alerts) == 1


class TestRuleRegistry:
    def test_15_rules_registered(self):
        assert len(ALL_RULES) == 15

    def test_unique_rule_ids(self):
        ids = [r.metadata.rule_id for r in ALL_RULES]
        assert len(ids) == len(set(ids))

    def test_all_rules_have_descriptions(self):
        for rule in ALL_RULES:
            assert rule.metadata.description
            assert rule.metadata.rule_name

    def test_rule_by_id_lookup(self):
        for rule in ALL_RULES:
            assert RULE_BY_ID[rule.metadata.rule_id] is rule

    def test_empty_txns_never_raises(self):
        account = _account()
        for rule in ALL_RULES:
            alerts = rule.evaluate(account, [], [])
            assert isinstance(alerts, list)

    def test_all_alerts_have_null_ground_truth(self):
        """No rule should set true_sar."""
        account = _account(pep=True, adverse=True, high_risk=True)
        txns = [
            make_cash_deposit("TEST", 9_500.0),
            make_cash_deposit("TEST", 9_200.0),
            make_cash_deposit("TEST", 8_800.0),
            make_intl_wire("TEST", 50_000.0, JurisdictionRisk.VERY_HIGH),
        ] * 10
        for rule in ALL_RULES:
            alerts = rule.evaluate(account, txns, txns)
            for alert in alerts:
                assert alert.true_sar is None, \
                    f"Rule {rule.metadata.rule_id} set true_sar={alert.true_sar}"
