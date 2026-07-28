"""Operational signals whose rates retain their numerator and denominator."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class RatioSnapshot:
    name: str
    numerator: int
    denominator: int
    ratio: float | None
    window: str
    target: float | None


class RatioMetric:
    def __init__(self, name: str, *, window: str, target: float | None = None) -> None:
        self.name = name
        self.window = window
        self.target = target
        self._good = 0
        self._valid = 0
        self._lock = Lock()

    def observe(self, *, good: bool, valid: bool = True) -> None:
        """Count a valid opportunity and whether it satisfied the stated criterion."""
        with self._lock:
            if valid:
                self._valid += 1
                self._good += int(good)

    def snapshot(self) -> RatioSnapshot:
        with self._lock:
            ratio = self._good / self._valid if self._valid else None
            return RatioSnapshot(
                name=self.name,
                numerator=self._good,
                denominator=self._valid,
                ratio=ratio,
                window=self.window,
                target=self.target,
            )


class OperationalMetrics:
    def __init__(self) -> None:
        self.vendor_projection = RatioMetric(
            "vendor_projection_success",
            window="rolling_30d",
            target=0.999,
        )
        self.reconciliation = RatioMetric(
            "ambiguous_write_reconciliation",
            window="rolling_30d",
            target=1.0,
        )
        self.instrument_acceptance = RatioMetric(
            "instrument_message_acceptance",
            window="rolling_24h",
        )

    def snapshots(self) -> tuple[RatioSnapshot, ...]:
        return (
            self.vendor_projection.snapshot(),
            self.reconciliation.snapshot(),
            self.instrument_acceptance.snapshot(),
        )

