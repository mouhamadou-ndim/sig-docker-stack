"""Point d'entrée en ligne de commande : `python -m sig_etl run|verify`."""

from __future__ import annotations

import argparse
import dataclasses
import logging
from collections.abc import Sequence

import psycopg

from .config import Settings, load_settings, parse_departements
from .extract import ExtractError, fetch_communes
from .load import load_communes
from .transform import clean_features
from .verify import Controle, verify_departement

log = logging.getLogger("sig_etl")


def _journaliser_controles(departement: str, controles: Sequence[Controle]) -> bool:
    for c in controles:
        log.log(
            logging.INFO if c.ok else logging.ERROR,
            "Département %s : contrôle %-18s %s (%s)",
            departement,
            c.nom,
            "OK" if c.ok else "ÉCHEC",
            c.detail,
        )
    return all(c.ok for c in controles)


def _run(settings: Settings, dry_run: bool) -> int:
    conn = None if dry_run else psycopg.connect()
    echecs = 0
    try:
        for departement in settings.departements:
            bruts = fetch_communes(settings, departement)
            resultat = clean_features(bruts, departement)
            log.info(
                "Département %s : %d extraites, %d valides, %d rejetées, %d doublons",
                departement,
                len(bruts),
                len(resultat.communes),
                len(resultat.rejets),
                resultat.doublons,
            )
            for rejet in resultat.rejets:
                log.warning("Rejet %s : %s", rejet.identifiant, rejet.motif)

            if not resultat.communes:
                log.error(
                    "Département %s : aucune commune exploitable, rien n'est chargé", departement
                )
                echecs += 1
                continue
            taux_rejet = len(resultat.rejets) / len(bruts)
            if taux_rejet > settings.max_reject_ratio:
                log.error(
                    "Département %s : taux de rejet %.1f %% supérieur au seuil %.1f %%, "
                    "rien n'est chargé",
                    departement,
                    100 * taux_rejet,
                    100 * settings.max_reject_ratio,
                )
                echecs += 1
                continue
            if conn is None:
                continue

            stats = load_communes(
                conn,
                departement,
                resultat.communes,
                extraites=len(bruts),
                rejetees=len(resultat.rejets),
            )
            log.info(
                "Département %s : %d chargées, %d supprimées",
                departement,
                stats.chargees,
                stats.supprimees,
            )
            controles = verify_departement(conn, departement, attendu=len(resultat.communes))
            if not _journaliser_controles(departement, controles):
                echecs += 1
    finally:
        if conn is not None:
            conn.close()
    return 1 if echecs else 0


def _verify(settings: Settings) -> int:
    echecs = 0
    with psycopg.connect() as conn:
        for departement in settings.departements:
            if not _journaliser_controles(departement, verify_departement(conn, departement)):
                echecs += 1
    return 1 if echecs else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sig-etl", description="ETL des communes IGN (ADMIN EXPRESS) vers PostGIS."
    )
    sub = parser.add_subparsers(dest="commande", required=True)
    p_run = sub.add_parser("run", help="extrait, nettoie, charge puis vérifie")
    p_run.add_argument("--dry-run", action="store_true", help="extrait et nettoie sans charger")
    p_verify = sub.add_parser("verify", help="contrôle les données déjà chargées")
    for p in (p_run, p_verify):
        p.add_argument("--departements", help='codes séparés par des virgules, ex. "91,94"')
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = load_settings()
        if args.departements:
            settings = dataclasses.replace(
                settings, departements=parse_departements(args.departements)
            )
    except ValueError as exc:
        parser.error(str(exc))

    try:
        if args.commande == "run":
            return _run(settings, args.dry_run)
        return _verify(settings)
    except (ExtractError, psycopg.Error) as exc:
        log.error("Échec du pipeline : %s", exc)
        return 1
