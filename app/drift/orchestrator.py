"""
Drift Orchestrator — iterates registered DriftSignal implementations.

Accepts new signal registrations without code changes. Layer 2 connection
drift signals (future) will implement the same DriftSignal interface.
"""
import logging
from datetime import datetime

from .signals import DriftSignal, DriftEvent, SchemaDrift, FreshnessDrift, CoverageDrift, VolumeDrift

_log = logging.getLogger("aam.drift.orchestrator")


class DriftOrchestrator:
    """Runs all registered drift signals and collects results."""

    def __init__(self):
        self._signals: list[DriftSignal] = []
        self._last_check: dict[str, datetime] = {}
        # Register Layer 1 signals by default
        self.register(SchemaDrift())
        self.register(FreshnessDrift())
        self.register(CoverageDrift())
        self.register(VolumeDrift())

    def register(self, signal: DriftSignal) -> None:
        """Register a new drift signal. Accepts any DriftSignal implementation."""
        self._signals.append(signal)
        _log.info("Drift signal registered: %s", type(signal).__name__)

    def detect_all(self, entity_id: str, run_id: str) -> list[DriftEvent]:
        """Run all registered signals and collect drift events.

        If a signal fails (PG timeout, connection error), skip it with error
        logged. Other signals still execute. Does NOT return fake 'no drift'.
        """
        all_events: list[DriftEvent] = []

        for signal in self._signals:
            signal_name = type(signal).__name__
            try:
                events = signal.detect(entity_id, run_id)
                all_events.extend(events)
                self._last_check[signal_name] = datetime.utcnow()
                _log.info(
                    "Drift signal %s: %d events for entity=%s run=%s",
                    signal_name, len(events), entity_id, run_id,
                )
            except Exception as exc:
                _log.error(
                    "Drift signal %s FAILED for entity=%s run=%s: %s — skipping, other signals continue",
                    signal_name, entity_id, run_id, exc,
                )

        return all_events

    def get_last_check_times(self) -> dict[str, str]:
        """Return last check timestamp per signal name."""
        return {
            name: ts.isoformat()
            for name, ts in self._last_check.items()
        }

    def get_signal_names(self) -> list[str]:
        """Return names of all registered signals."""
        return [type(s).__name__ for s in self._signals]
