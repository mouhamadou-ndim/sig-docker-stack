"""Contrôles de qualité exécutés sur les données chargées dans PostGIS."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

# Emprise large de la France métropolitaine en Lambert-93 (xmin, ymin, xmax, ymax).
EMPRISE_L93 = (0, 6_000_000, 1_300_000, 7_200_000)

VERIFY_SQL = """
SELECT count(*),
       count(*) FILTER (WHERE NOT ST_IsValid(geom)),
       count(*) FILTER (WHERE ST_SRID(geom) <> 2154),
       count(*) FILTER (WHERE NOT ST_Covers(ST_MakeEnvelope(%s, %s, %s, %s, 2154), geom)),
       count(*) FILTER (WHERE ST_Area(geom) <= 0),
       count(*) FILTER (WHERE btrim(nom) = '')
FROM ref.communes
WHERE code_departement = %s
"""


@dataclass(frozen=True)
class Controle:
    nom: str
    ok: bool
    detail: str


def build_controles(row: tuple[int, ...], attendu: int | None = None) -> list[Controle]:
    lignes, invalides, mauvais_srid, hors_emprise, surface_nulle, sans_nom = row
    if attendu is None:
        presence = Controle("presence", lignes > 0, f"{lignes} communes")
    else:
        presence = Controle(
            "presence", lignes == attendu, f"{lignes} communes, {attendu} attendues"
        )
    return [
        presence,
        Controle("geometries_valides", invalides == 0, f"{invalides} géométries invalides"),
        Controle("srid_2154", mauvais_srid == 0, f"{mauvais_srid} géométries hors EPSG:2154"),
        Controle("emprise_france", hors_emprise == 0, f"{hors_emprise} géométries hors emprise"),
        Controle("surface_positive", surface_nulle == 0, f"{surface_nulle} surfaces nulles"),
        Controle("nom_renseigne", sans_nom == 0, f"{sans_nom} communes sans nom"),
    ]


def verify_departement(
    conn: psycopg.Connection, departement: str, attendu: int | None = None
) -> list[Controle]:
    with conn.cursor() as cur:
        cur.execute(VERIFY_SQL, (*EMPRISE_L93, departement))
        row = cur.fetchone()
    return build_controles(row, attendu)
