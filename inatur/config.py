"""Innlasting av config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import DogStatus

DEFAULT_PATH = Path("config.yaml")


@dataclass
class Config:
    # Hvilke hundestatuser som skal rapporteres.
    report_dog_statuses: list[str] = field(
        default_factory=lambda: ["allowed", "conditional", "unclear", "no_mention"]
    )
    # Krev at tilbudet gjelder minst én fugleart.
    require_birds: bool = True
    # Rapporter kun li-/fjellrype.
    priority_only: bool = False
    max_price: int | None = None
    fylker: list[str] = field(default_factory=list)

    delay: float = 1.5
    max_pages: int = 40
    respect_robots: bool = True

    db_path: str = "state.db"
    report_path: str = "reports/latest.txt"

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> "Config":
        p = Path(path)
        if not p.exists():
            return cls()
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

        filters = data.get("filters", {}) or {}
        scraping = data.get("scraping", {}) or {}
        output = data.get("output", {}) or {}

        return cls(
            report_dog_statuses=filters.get(
                "dog_statuses", cls().report_dog_statuses
            ),
            require_birds=filters.get("require_birds", True),
            priority_only=filters.get("priority_only", False),
            max_price=filters.get("max_price"),
            fylker=filters.get("fylker", []) or [],
            delay=scraping.get("delay", 1.5),
            max_pages=scraping.get("max_pages", 40),
            respect_robots=scraping.get("respect_robots", True),
            db_path=output.get("db_path", "state.db"),
            report_path=output.get("report_path", "reports/latest.txt"),
        )

    @property
    def dog_statuses(self) -> set[DogStatus]:
        return {DogStatus(s) for s in self.report_dog_statuses}
