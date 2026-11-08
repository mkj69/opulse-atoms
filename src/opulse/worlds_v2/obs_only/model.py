"""Public immutable inputs shared by the fixed kernel and independent reference."""

from dataclasses import dataclass

SIZE = 64
ROUTES = ("RRRR", "RRR", "RR", "R", "S")


@dataclass(frozen=True)
class PublicConfig:
    prior: str = "uniform"
    protocol: str = "legacy"
    region: tuple[int, ...] = tuple(range(24, 40))
    routes: tuple[str, ...] = ROUTES
    risk_mode: str = "ever"
    credible_mode: str = "ranked"

    def __post_init__(self):
        if self.prior not in ("uniform", "edge", "even"):
            raise ValueError("unknown prior")
        if self.protocol not in ("legacy", "sharp", "parity"):
            raise ValueError("unknown protocol")
        if self.risk_mode not in ("ever", "terminal", "at_least_two"):
            raise ValueError("unknown risk mode")
        if self.credible_mode not in ("ranked", "window"):
            raise ValueError("unknown credible mode")
        if not self.region or len(self.region) > SIZE or len(set(self.region)) != len(self.region) or any(not isinstance(cell, int) or not 0 <= cell < SIZE for cell in self.region):
            raise ValueError("invalid public hazard region")
        if not 1 <= len(self.routes) <= 8 or len(set(self.routes)) != len(self.routes) or any(not route or len(route) > 4 or any(action not in "LRS" for action in route) for route in self.routes):
            raise ValueError("invalid public route menu")


DEFAULT = PublicConfig()


@dataclass(frozen=True)
class Trace:
    actions: str
    readings: str

    def __post_init__(self):
        if len(self.actions) + 1 != len(self.readings):
            raise ValueError("one initial reading and one per action required")
        if len(self.readings) > 81 or any(action not in "LRS" for action in self.actions):
            raise ValueError("invalid action tape or horizon")
        if any(reading not in "01234567" for reading in self.readings):
            raise ValueError("invalid sensor alphabet")


@dataclass(frozen=True)
class State:
    position: int
    history: Trace
    private_draws: tuple[int, ...]
