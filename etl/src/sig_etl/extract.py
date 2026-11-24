"""Extraction des communes depuis le service WFS de la Géoplateforme IGN."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import requests

from .config import Settings

log = logging.getLogger(__name__)

MAX_PAGES = 1000


class ExtractError(RuntimeError):
    """L'extraction a échoué ou est incomplète."""


class _Retryable(Exception):
    pass


def _fetch_page(
    session: requests.Session,
    settings: Settings,
    params: dict[str, Any],
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(1, settings.http_retries + 1):
        try:
            resp = session.get(settings.wfs_url, params=params, timeout=settings.http_timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise _Retryable(f"HTTP {resp.status_code}")
            if resp.status_code != 200:
                raise ExtractError(
                    f"Le WFS a refusé la requête (HTTP {resp.status_code}) : {resp.text[:300]}"
                )
            # Le service répond parfois en HTTP 200 avec un corps qui n'est pas du JSON.
            try:
                payload = resp.json()
            except ValueError as exc:
                raise _Retryable(f"réponse non JSON : {resp.text[:200]!r}") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
                raise _Retryable("réponse JSON sans liste 'features'")
            return payload
        except (requests.RequestException, _Retryable) as exc:
            last = exc
            if attempt < settings.http_retries:
                delay = min(2**attempt, 30)
                log.warning(
                    "Tentative %d/%d échouée (%s), nouvel essai dans %ds",
                    attempt,
                    settings.http_retries,
                    exc,
                    delay,
                )
                sleep(delay)
    raise ExtractError(f"Échec après {settings.http_retries} tentatives : {last}") from last


def fetch_communes(
    settings: Settings,
    departement: str,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Retourne toutes les communes d'un département (entités GeoJSON, EPSG:4326)."""
    own_session = session is None
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = "sig-etl/0.1"

    features: list[dict[str, Any]] = []
    attendu: int | None = None
    try:
        for page in range(MAX_PAGES):
            payload = _fetch_page(
                session,
                settings,
                {
                    "SERVICE": "WFS",
                    "VERSION": "2.0.0",
                    "REQUEST": "GetFeature",
                    "TYPENAMES": settings.wfs_typename,
                    "OUTPUTFORMAT": "application/json",
                    "SRSNAME": "EPSG:4326",
                    "CQL_FILTER": f"code_insee_du_departement='{departement}'",
                    # Un tri explicite garantit une pagination stable.
                    "SORTBY": "code_insee",
                    "COUNT": settings.page_size,
                    "STARTINDEX": page * settings.page_size,
                },
                sleep,
            )
            batch = payload["features"]
            features.extend(batch)
            matched = payload.get("numberMatched", payload.get("totalFeatures"))
            if isinstance(matched, int) and not isinstance(matched, bool):
                attendu = matched
            log.info("Département %s : page %d, %d entités", departement, page + 1, len(batch))
            if len(batch) < settings.page_size or (
                attendu is not None and len(features) >= attendu
            ):
                break
        else:
            raise ExtractError(f"Pagination interrompue après {MAX_PAGES} pages")
    finally:
        if own_session:
            session.close()

    if attendu is not None and len(features) != attendu:
        raise ExtractError(
            f"Extraction incomplète : {len(features)} entités reçues, {attendu} annoncées"
        )
    return features
