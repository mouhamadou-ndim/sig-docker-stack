import pytest

from sig_etl.config import parse_departements
from sig_etl.transform import clean_feature, clean_features

CARRE = [[2.0, 48.0], [2.1, 48.0], [2.1, 48.1], [2.0, 48.1], [2.0, 48.0]]


def feature(code="91377", geometry=None, **props):
    base = {
        "nom_officiel": "  Massy ",
        "statut": "Commune simple",
        "code_insee": code,
        "population": 50000,
        "code_insee_du_departement": "91",
        "code_insee_de_la_region": "11",
        "code_postal": "91300",
        "superficie_cadastrale": 943,
    }
    base.update(props)
    if geometry is None:
        geometry = {"type": "MultiPolygon", "coordinates": [[CARRE]]}
    return {"type": "Feature", "id": f"commune.{code}", "properties": base, "geometry": geometry}


def test_clean_feature_normalise_attributs_et_geometrie():
    brut = feature(
        geometry={"type": "Polygon", "coordinates": [[[x, y, 12.5] for x, y in CARRE]]},
        population="50000",
        code_postal="91",
        superficie_cadastrale=-3,
    )

    commune = clean_feature(brut, "91")

    assert commune.nom == "Massy"
    assert commune.population == 50000
    assert commune.code_postal is None
    assert commune.superficie_ha is None
    assert commune.geometry == {"type": "MultiPolygon", "coordinates": [[CARRE]]}


@pytest.mark.parametrize(
    ("brut", "motif"),
    [
        (feature(code="9137"), "code INSEE invalide"),
        (feature(nom_officiel="   "), "nom officiel absent"),
        (feature(code_insee_du_departement="94"), "hors périmètre"),
        ({"type": "Feature", "properties": feature()["properties"], "geometry": None}, "absente"),
        (feature(geometry={"type": "Point", "coordinates": [2.0, 48.0]}), "inattendu"),
        (feature(geometry={"type": "Polygon", "coordinates": [CARRE[:3]]}), "moins de 4"),
        (feature(geometry={"type": "Polygon", "coordinates": [CARRE[:4]]}), "non fermé"),
        (
            feature(geometry={"type": "Polygon", "coordinates": [[[y, x] for x, y in CARRE]]}),
            "hors de l'emprise",
        ),
    ],
)
def test_clean_features_rejette_les_entites_inexploitables(brut, motif):
    resultat = clean_features([brut], "91")

    assert resultat.communes == []
    assert len(resultat.rejets) == 1
    assert motif in resultat.rejets[0].motif


def test_clean_features_dedoublonne_et_conserve_les_valides():
    resultat = clean_features([feature("91377"), feature("91377"), feature("91312")], "91")

    assert [c.code_insee for c in resultat.communes] == ["91377", "91312"]
    assert resultat.doublons == 1
    assert resultat.rejets == []


def test_parse_departements():
    assert parse_departements(" 91, 2a ,91") == ("91", "2A")
    for invalide in ("", "971", "9"):
        with pytest.raises(ValueError):
            parse_departements(invalide)
