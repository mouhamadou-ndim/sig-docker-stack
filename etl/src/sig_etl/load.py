"""Chargement des communes dans PostGIS (ref.communes)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from .transform import Commune

# La reprojection et la réparation des géométries sont confiées à PostGIS.
UPSERT_SQL = """
INSERT INTO ref.communes (
    code_insee, nom, statut, code_departement, code_region, code_postal,
    population, superficie_ha, date_chargement, geom
) VALUES (
    %(code_insee)s, %(nom)s, %(statut)s, %(code_departement)s, %(code_region)s, %(code_postal)s,
    %(population)s, %(superficie_ha)s, now(),
    ST_Multi(ST_CollectionExtract(ST_MakeValid(
        ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s::text), 4326), 2154)
    ), 3))
)
ON CONFLICT (code_insee) DO UPDATE SET
    nom = EXCLUDED.nom,
    statut = EXCLUDED.statut,
    code_departement = EXCLUDED.code_departement,
    code_region = EXCLUDED.code_region,
    code_postal = EXCLUDED.code_postal,
    population = EXCLUDED.population,
    superficie_ha = EXCLUDED.superficie_ha,
    date_chargement = EXCLUDED.date_chargement,
    geom = EXCLUDED.geom
"""

# Les communes disparues de la source (fusions) sont retirées du département.
DELETE_SQL = """
DELETE FROM ref.communes
WHERE code_departement = %s AND code_insee <> ALL(%s::text[])
"""

JOURNAL_SQL = """
INSERT INTO ref.etl_runs (departement, lignes_extraites, lignes_rejetees, lignes_chargees,
                          lignes_supprimees)
VALUES (%s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class LoadStats:
    chargees: int
    supprimees: int


def load_communes(
    conn: psycopg.Connection,
    departement: str,
    communes: Sequence[Commune],
    *,
    extraites: int,
    rejetees: int,
) -> LoadStats:
    """Charge un département dans une transaction unique (tout ou rien)."""
    if not communes:
        raise ValueError("refus de charger un lot vide : il viderait le département")

    lignes = [
        {
            "code_insee": c.code_insee,
            "nom": c.nom,
            "statut": c.statut,
            "code_departement": c.code_departement,
            "code_region": c.code_region,
            "code_postal": c.code_postal,
            "population": c.population,
            "superficie_ha": c.superficie_ha,
            "geometry": json.dumps(c.geometry),
        }
        for c in communes
    ]
    codes = [c.code_insee for c in communes]

    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, lignes)
        cur.execute(DELETE_SQL, (departement, codes))
        supprimees = cur.rowcount
        cur.execute(JOURNAL_SQL, (departement, extraites, rejetees, len(lignes), supprimees))
    return LoadStats(chargees=len(lignes), supprimees=supprimees)
