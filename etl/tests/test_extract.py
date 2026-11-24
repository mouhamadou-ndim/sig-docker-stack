import pytest

from sig_etl.config import Settings
from sig_etl.extract import ExtractError, fetch_communes


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("pas du JSON")
        return self._payload


class FakeSession:
    """Rejoue une liste de réponses et mémorise les paramètres reçus."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        return self.responses.pop(0)


def page(n, matched):
    return FakeResponse(
        payload={"features": [{"id": i} for i in range(n)], "numberMatched": matched}
    )


SETTINGS = Settings(page_size=2, http_retries=3)


def test_fetch_communes_parcourt_toutes_les_pages():
    session = FakeSession([page(2, 5), page(2, 5), page(1, 5)])

    features = fetch_communes(SETTINGS, "91", session=session)

    assert len(features) == 5
    assert [c["STARTINDEX"] for c in session.calls] == [0, 2, 4]
    assert session.calls[0]["CQL_FILTER"] == "code_insee_du_departement='91'"


def test_fetch_communes_reessaie_sur_reponse_non_json_et_erreur_serveur():
    session = FakeSession([FakeResponse(text="<html>"), FakeResponse(status_code=503), page(1, 1)])
    pauses = []

    features = fetch_communes(SETTINGS, "91", session=session, sleep=pauses.append)

    assert len(features) == 1
    assert len(pauses) == 2


def test_fetch_communes_abandonne_apres_le_nombre_maximal_de_tentatives():
    session = FakeSession([FakeResponse(status_code=503)] * 3)

    with pytest.raises(ExtractError, match="3 tentatives"):
        fetch_communes(SETTINGS, "91", session=session, sleep=lambda _: None)


def test_fetch_communes_echoue_sans_reessayer_sur_requete_refusee():
    session = FakeSession([FakeResponse(status_code=400, text="Illegal property name")])

    with pytest.raises(ExtractError, match="Illegal property name"):
        fetch_communes(SETTINGS, "91", session=session)
    assert len(session.calls) == 1


def test_fetch_communes_detecte_une_extraction_incomplete():
    session = FakeSession([page(2, 5), page(1, 5)])

    with pytest.raises(ExtractError, match="incomplète"):
        fetch_communes(SETTINGS, "91", session=session)
