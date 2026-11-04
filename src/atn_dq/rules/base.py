"""Basisklassen für die Regel-Engine.

Jede Regel ist eine kleine Klasse, die ``run(pkg, cfg)`` implementiert und eine
Liste von :class:`Finding` zurückliefert. Regeln werden über einen Dekorator
registriert, so dass neue Regeln einfach ergänzt werden können.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from ..config import Config
from ..finding import Finding
from ..loader import DataPackage


@dataclass
class Rule:
    rule_id: str
    name: str
    description: str
    category: str
    dimension: str
    default_severity: str
    func: Callable[[DataPackage, Config], Iterable[Finding]]
    enabled: bool = True

    def run(self, pkg: DataPackage, cfg: Config) -> list[Finding]:
        return list(self.func(pkg, cfg))


class RuleRegistry:
    """Zentrales Register aller bekannten Regeln."""

    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}

    def register(
        self,
        *,
        rule_id: str,
        name: str,
        description: str,
        category: str,
        dimension: str,
        default_severity: str = "mittel",
    ) -> Callable[[Callable], Callable]:
        def decorator(func: Callable[[DataPackage, Config], Iterable[Finding]]):
            if rule_id in self._rules:
                raise ValueError(f"Regel {rule_id} bereits registriert")
            self._rules[rule_id] = Rule(
                rule_id=rule_id,
                name=name,
                description=description,
                category=category,
                dimension=dimension,
                default_severity=default_severity,
                func=func,
            )
            return func
        return decorator

    def all(self) -> list[Rule]:
        return sorted(self._rules.values(), key=lambda r: r.rule_id)

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)

    def set_enabled(self, rule_id: str, enabled: bool) -> None:
        if rule_id in self._rules:
            self._rules[rule_id].enabled = enabled

    def __len__(self) -> int:
        return len(self._rules)


registry = RuleRegistry()
