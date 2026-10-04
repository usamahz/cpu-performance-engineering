"""site.toml, copy.toml and charts.toml, loaded once."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import SITE_ROOT


class Copy(dict):
    """Nested copy strings with attribute access for templates: copy.home.heading."""

    def __getattr__(self, name):
        try:
            value = self[name]
        except KeyError as exc:  # a missing string is a build error, not a blank
            raise AttributeError(f"copy.toml has no key {name!r}") from exc
        return Copy(value) if isinstance(value, dict) else value


@dataclass
class Config:
    site: dict
    nav: list[dict]
    groups: list[dict]
    reserved: dict
    budgets: dict
    copy: Copy
    charts: list[dict]
    base_url: str

    @property
    def repo(self) -> str:
        return self.site["repo"]


def load_config(base_url: str | None = None, root: Path = SITE_ROOT) -> Config:
    site = tomllib.loads((root / "site.toml").read_text(encoding="utf-8"))
    copy = tomllib.loads((root / "copy.toml").read_text(encoding="utf-8"))
    charts_path = root / "charts.toml"
    charts = tomllib.loads(charts_path.read_text(encoding="utf-8")).get("chart", []) if charts_path.is_file() else []
    url = (base_url or site["site"]["default_base_url"]).rstrip("/")
    return Config(
        site=site["site"],
        nav=site["nav"],
        groups=site["groups"],
        reserved=site["reserved"],
        budgets=site["budgets"],
        copy=Copy(copy),
        charts=charts,
        base_url=url,
    )
