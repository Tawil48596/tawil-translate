import pytest

from tawil_translate.application.budget import BudgetExceeded, DailyTokenBudget


def test_budget_opens_circuit_before_limit_is_crossed() -> None:
    budget = DailyTokenBudget(limit=3)
    budget.reserve(2)
    with pytest.raises(BudgetExceeded):
        budget.reserve(2)
    assert budget.used == 2

