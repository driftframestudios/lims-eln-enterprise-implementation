"""Complete bounded owned cleanup while retaining control and local diagnostics."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CleanupFailure:
    stage: str
    error: BaseException


class Cleanup:
    """One invocation's constant-count release attempts, in ownership order.

    Callers select the resources, transaction/publication policy and ordinary
    error type. Exception objects stay local; notes contain stage and type only.
    Each action is attempted once, including after a control interruption.
    """

    def __init__(self) -> None:
        self._failures: list[CleanupFailure] = []

    def attempt(self, stage: str, action: Callable[[], object]) -> None:
        try:
            action()
        except BaseException as error:
            self._failures.append(CleanupFailure(stage, error))

    def retain_on(self, error: BaseException) -> None:
        """Keep cleanup diagnostics on a cause before its owner translates it."""
        previous = getattr(error, "cleanup_failures", ())
        error.cleanup_failures = (*previous, *self._failures)
        for failure in self._failures:
            error.add_note(f"Cleanup {failure.stage} raised {type(failure.error).__name__}")

    def finish(
        self,
        primary: BaseException | None,
        ordinary_error: Callable[[], Exception],
    ) -> None:
        """Preserve the first control signal, then primary, then ordinary error.

        A caller with a primary exception continues its active raise when this
        method returns. Selected exceptions expose cleanup_failures and, when
        another exception is selected, primary_error for local reconciliation.
        """
        if not self._failures:
            return
        control = primary if primary is not None and not isinstance(primary, Exception) else next(
            (failure.error for failure in self._failures
             if not isinstance(failure.error, Exception)), None,
        )
        selected = control if control is not None else primary
        if selected is None:
            selected = ordinary_error()
        self.retain_on(selected)
        if selected is primary:
            return
        selected.primary_error = primary
        cause = primary if primary is not None else next(
            (failure.error for failure in self._failures if failure.error is not selected), None,
        )
        raise selected from cause
