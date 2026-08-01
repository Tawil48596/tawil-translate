from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    pass


@dataclass(slots=True)
class DailyTokenBudget:
    limit: int
    used: int = 0

    def reserve(self, estimated_tokens: int) -> None:
        if estimated_tokens < 0:
            raise ValueError("estimated_tokens must be non-negative")
        if self.used + estimated_tokens > self.limit:
            raise BudgetExceeded(f"daily token budget exceeded ({self.used}/{self.limit})")
        self.used += estimated_tokens

    @staticmethod
    def estimate(text: str) -> int:
        # Conservative mixed CJK/Latin estimate; provider usage should reconcile this later.
        return max(1, (len(text) + 2) // 3)

