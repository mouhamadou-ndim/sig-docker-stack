-- Schéma de référence alimenté par l'ETL et publié par GeoServer.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA ref;

CREATE TABLE ref.communes (
    code_insee       varchar(5)  PRIMARY KEY,
    nom              text        NOT NULL CHECK (btrim(nom) <> ''),
    statut           text,
    code_departement varchar(3)  NOT NULL,
    code_region      varchar(3),
    code_postal      varchar(5),
    population       integer     CHECK (population >= 0),
    superficie_ha    integer     CHECK (superficie_ha >= 0),
    source           text        NOT NULL DEFAULT 'IGN ADMIN EXPRESS COG',
    date_chargement  timestamptz NOT NULL DEFAULT now(),
    geom             geometry(MultiPolygon, 2154) NOT NULL,
    CONSTRAINT communes_geom_valide CHECK (ST_IsValid(geom) AND NOT ST_IsEmpty(geom))
);

CREATE INDEX communes_geom_gix ON ref.communes USING gist (geom);
CREATE INDEX communes_departement_idx ON ref.communes (code_departement);

-- Journal des exécutions de l'ETL
CREATE TABLE ref.etl_runs (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    execute_le        timestamptz NOT NULL DEFAULT now(),
    departement       varchar(3)  NOT NULL,
    lignes_extraites  integer     NOT NULL,
    lignes_rejetees   integer     NOT NULL,
    lignes_chargees   integer     NOT NULL,
    lignes_supprimees integer     NOT NULL
);

-- Moindre privilège : l'ETL écrit, GeoServer ne fait que lire.
GRANT USAGE ON SCHEMA ref TO etl_writer, geoserver_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON ref.communes TO etl_writer;
GRANT SELECT, INSERT ON ref.etl_runs TO etl_writer;
GRANT SELECT ON ref.communes TO geoserver_ro;
