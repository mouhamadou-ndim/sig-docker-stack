"""Tests de bout en bout sur la stack démarrée.

Prérequis : `docker compose up -d --wait`, ETL exécuté et couche publiée.
À lancer depuis la racine du dépôt : `pytest tests/stack`.
"""

import json
import os
import subprocess

import pytest
import requests

BASE_URL = os.environ.get("STACK_BASE_URL", "http://localhost:8080")
PROJECT = "sig-stack"
LAYER = "sig:communes"


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)


def container_id(service):
    cid = docker("compose", "ps", "-q", service).stdout.strip()
    assert cid, f"le service {service} n'est pas démarré"
    return cid


def inspect(service, template):
    result = docker("inspect", "-f", template, container_id(service))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def host_ports(service):
    ports = inspect(service, "{{json .NetworkSettings.Ports}}") or {}
    return {port for port, bindings in ports.items() if bindings}


def get(path, **kwargs):
    return requests.get(BASE_URL + path, timeout=60, **kwargs)


def db_count():
    result = docker(
        "compose",
        "exec",
        "-T",
        "postgis",
        "sh",
        "-c",
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM ref.communes"',
    )
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


# --- Cloisonnement réseau -------------------------------------------------


def test_chaque_service_est_sur_ses_seuls_reseaux():
    def networks(service):
        return set(inspect(service, "{{json .NetworkSettings.Networks}}"))

    assert networks("nginx") == {f"{PROJECT}_edge", f"{PROJECT}_frontend"}
    assert networks("geoserver") == {f"{PROJECT}_frontend", f"{PROJECT}_backend"}
    assert networks("postgis") == {f"{PROJECT}_backend"}


@pytest.mark.parametrize("network", ["frontend", "backend"])
def test_reseaux_applicatifs_sans_acces_exterieur(network):
    result = docker("network", "inspect", "-f", "{{.Internal}}", f"{PROJECT}_{network}")

    assert result.stdout.strip() == "true", result.stderr


def test_seul_nginx_publie_un_port_sur_l_hote():
    assert host_ports("nginx") == {"8080/tcp"}
    assert host_ports("geoserver") == set()
    assert host_ports("postgis") == set()


def test_nginx_joint_geoserver_mais_pas_postgis():
    def connexion(hote, port):
        return docker("compose", "exec", "-T", "nginx", "nc", "-z", "-w", "3", hote, port)

    assert connexion("geoserver", "8080").returncode == 0
    assert connexion("postgis", "5432").returncode != 0


# --- Durcissement de Nginx ------------------------------------------------


def test_healthz():
    assert get("/healthz").status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/geoserver/web/",
        "/geoserver/rest/workspaces.json",
        "/geoserver/rest/about/version.json",
        "/geoserver/index.html",
    ],
)
def test_administration_non_exposee(path):
    assert get(path, allow_redirects=False).status_code == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_methodes_d_ecriture_refusees(method):
    response = requests.request(method, BASE_URL + "/geoserver/wfs", data="<x/>", timeout=30)

    assert response.status_code == 403


def test_en_tetes_de_securite():
    response = get(
        "/geoserver/ows",
        params={"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"},
    )

    assert response.status_code == 200
    assert response.headers["Server"] == "nginx"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "X-Powered-By" not in response.headers


def test_capacites_annoncent_l_url_publique():
    response = get(
        "/geoserver/sig/ows",
        params={"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"},
    )

    assert response.status_code == 200
    assert f"{BASE_URL}/geoserver/" in response.text, response.text[:1500]


# --- Chaîne complète : IGN -> PostGIS -> GeoServer -> Nginx ------------------


def test_wfs_sert_les_communes_chargees_par_l_etl():
    response = get(
        "/geoserver/sig/ows",
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": LAYER,
            "outputFormat": "application/json",
            "count": 5,
        },
    )

    assert response.status_code == 200, response.text[:500]
    data = response.json()
    total = db_count()
    assert total > 0
    assert data.get("numberMatched", data.get("totalFeatures")) == total
    assert len(data["features"]) == min(5, total)
    first = data["features"][0]
    assert first["geometry"]["type"] == "MultiPolygon"
    assert len(first["properties"]["code_insee"]) == 5


def test_wms_rend_une_image():
    response = get(
        "/geoserver/sig/wms",
        params={
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": LAYER,
            "styles": "",
            "srs": "EPSG:4326",
            "bbox": "1.9,48.2,2.7,48.8",
            "width": 256,
            "height": 192,
            "format": "image/png",
        },
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("image/png"), response.text[:500]
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
