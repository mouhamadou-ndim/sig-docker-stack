"""Nettoyage et normalisation des entités brutes (fonctions pures, sans E/S)."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, NamedTuple

CODE_INSEE_RE = re.compile(r"^(?:\d{2}|2[AB])\d{3}$")
CODE_POSTAL_RE = re.compile(r"^\d{5}$")

# Emprise de la France métropolitaine en EPSG:4326. Plus stricte que les bornes
# WGS 84, elle détecte aussi une inversion longitude/latitude.
LON_MIN, LON_MAX = -6.0, 10.5
LAT_MIN, LAT_MAX = 41.0, 51.6


@dataclass(frozen=True)
class Commune:
    code_insee: str
    nom: str
    statut: str | None
    code_departement: str
    code_region: str | None
    code_postal: str | None
    population: int | None
    superficie_ha: int | None
    geometry: dict[str, Any]  # GeoJSON MultiPolygon 2D, EPSG:4326


class Rejet(NamedTuple):
    identifiant: str
    motif: str


@dataclass
class TransformResult:
    communes: list[Commune] = field(default_factory=list)
    rejets: list[Rejet] = field(default_factory=list)
    doublons: int = 0


class _Invalide(ValueError):
    pass


def _texte(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()) or None


def _entier_positif(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    elif isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _anneau(ring: Any) -> list[list[float]]:
    if not isinstance(ring, list) or len(ring) < 4:
        raise _Invalide("anneau de moins de 4 sommets")
    points: list[list[float]] = []
    for position in ring:
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            raise _Invalide("sommet mal formé")
        x, y = position[0], position[1]
        for v in (x, y):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise _Invalide("coordonnée non numérique")
        if not (LON_MIN <= x <= LON_MAX and LAT_MIN <= y <= LAT_MAX):
            raise _Invalide("coordonnées hors de l'emprise de la France métropolitaine")
        points.append([x, y])
    if points[0] != points[-1]:
        raise _Invalide("anneau non fermé")
    return points


def normaliser_geometrie(geometry: Any) -> dict[str, Any]:
    """Valide la structure et retourne un MultiPolygon 2D."""
    if not isinstance(geometry, dict):
        raise _Invalide("géométrie absente")
    gtype, coords = geometry.get("type"), geometry.get("coordinates")
    if gtype == "Polygon":
        polygones = [coords]
    elif gtype == "MultiPolygon":
        polygones = coords
    else:
        raise _Invalide(f"type de géométrie inattendu : {gtype}")
    if not isinstance(polygones, list) or not polygones:
        raise _Invalide("géométrie vide")
    sortie = []
    for polygone in polygones:
        if not isinstance(polygone, list) or not polygone:
            raise _Invalide("polygone vide")
        sortie.append([_anneau(ring) for ring in polygone])
    return {"type": "MultiPolygon", "coordinates": sortie}


def clean_feature(feature: Any, departement: str | None = None) -> Commune:
    """Nettoie une entité ; lève ValueError (motif lisible) si elle est inexploitable."""
    props = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(props, dict):
        raise _Invalide("entité sans attributs")

    code_insee = (_texte(props.get("code_insee")) or "").upper()
    if not CODE_INSEE_RE.match(code_insee):
        raise _Invalide(f"code INSEE invalide : {code_insee!r}")

    nom = _texte(props.get("nom_officiel"))
    if not nom:
        raise _Invalide("nom officiel absent")

    code_departement = (_texte(props.get("code_insee_du_departement")) or code_insee[:2]).upper()
    if departement is not None and code_departement != departement:
        raise _Invalide(f"hors périmètre : département {code_departement}")

    code_postal = _texte(props.get("code_postal"))
    if code_postal is not None and not CODE_POSTAL_RE.match(code_postal):
        code_postal = None

    return Commune(
        code_insee=code_insee,
        nom=nom,
        statut=_texte(props.get("statut")),
        code_departement=code_departement,
        code_region=_texte(props.get("code_insee_de_la_region")),
        code_postal=code_postal,
        population=_entier_positif(props.get("population")),
        superficie_ha=_entier_positif(props.get("superficie_cadastrale")),
        geometry=normaliser_geometrie(feature.get("geometry")),
    )


def _identifiant(feature: Any) -> str:
    if isinstance(feature, dict):
        props = feature.get("properties")
        if isinstance(props, dict) and props.get("code_insee"):
            return str(props["code_insee"])
        if feature.get("id"):
            return str(feature["id"])
    return "?"


def clean_features(features: Iterable[Any], departement: str | None = None) -> TransformResult:
    """Nettoie un lot : écarte les entités invalides et dédoublonne sur le code INSEE."""
    resultat = TransformResult()
    vus: set[str] = set()
    for feature in features:
        try:
            commune = clean_feature(feature, departement)
        except _Invalide as exc:
            resultat.rejets.append(Rejet(_identifiant(feature), str(exc)))
            continue
        if commune.code_insee in vus:
            resultat.doublons += 1
            continue
        vus.add(commune.code_insee)
        resultat.communes.append(commune)
    return resultat
