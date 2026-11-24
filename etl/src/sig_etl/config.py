"""Configuration du pipeline, lue depuis les variables d'environnement.

La connexion PostgreSQL n'est pas gérée ici : psycopg lit directement les
variables standard de libpq (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

# Départements de métropole uniquement : le stockage est en Lambert-93 (EPSG:2154).
DEPARTEMENT_RE = re.compile(r"^(?:0[1-9]|[1-8]\d|9[0-5]|2[AB])$")


@dataclass(frozen=True)
class Settings:
    wfs_url: str = "https://data.geopf.fr/wfs/ows"
    wfs_typename: str = "ADMINEXPRESS-COG.LATEST:commune"
    departements: tuple[str, ...] = ("91",)
    page_size: int = 500
    http_timeout: float = 60.0
    http_retries: int = 4
    max_reject_ratio: float = 0.05


def parse_departements(raw: str) -> tuple[str, ...]:
    """Transforme "91, 94" en ("91", "94") en validant chaque code."""
    codes = tuple(dict.fromkeys(c.strip().upper() for c in raw.split(",") if c.strip()))
    if not codes:
        raise ValueError("aucun département fourni")
    for code in codes:
        if not DEPARTEMENT_RE.match(code):
            raise ValueError(f"code de département invalide : {code!r} (métropole attendue)")
    return codes


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    defaults = Settings()
    page_size = int(env.get("ETL_PAGE_SIZE", defaults.page_size))
    max_reject_ratio = float(env.get("ETL_MAX_REJECT_RATIO", defaults.max_reject_ratio))
    if page_size < 1:
        raise ValueError("ETL_PAGE_SIZE doit être supérieur ou égal à 1")
    if not 0 <= max_reject_ratio <= 1:
        raise ValueError("ETL_MAX_REJECT_RATIO doit être compris entre 0 et 1")
    return Settings(
        wfs_url=env.get("ETL_WFS_URL", defaults.wfs_url),
        wfs_typename=env.get("ETL_WFS_TYPENAME", defaults.wfs_typename),
        departements=parse_departements(
            env.get("ETL_DEPARTEMENTS", ",".join(defaults.departements))
        ),
        page_size=page_size,
        max_reject_ratio=max_reject_ratio,
    )
