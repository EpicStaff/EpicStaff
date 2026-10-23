-- Weather 0.7.0: saved places keep the order they were saved in, and each place keeps its
-- current temperature, which the backend looks up at Open-Meteo (weather_plugin.current_conditions).
--
-- The node runs this file while Weather is offline for the upgrade, after it backed the
-- database up, in one transaction, as the plugin's owner role.

-- Where a place is in its organization's list: 1 for the first one saved. A new place gets
-- the organization's highest position plus one (weather_plugin.places).
ALTER TABLE weather.saved_places ADD COLUMN position integer;

-- Number the places saved before this version, in the order they were saved. FORCE applies
-- the organization policy to the owner as well, and this transaction sets no organization, so
-- the UPDATE would see no row: lift FORCE for this transaction only, and put it back at once.
ALTER TABLE weather.saved_places NO FORCE ROW LEVEL SECURITY;
UPDATE weather.saved_places AS place SET position = numbered.position
  FROM (SELECT id, row_number() OVER (PARTITION BY org_id ORDER BY created_at, id) AS position
        FROM weather.saved_places) AS numbered
  WHERE place.id = numbered.id;
ALTER TABLE weather.saved_places FORCE ROW LEVEL SECURITY;

ALTER TABLE weather.saved_places ALTER COLUMN position SET NOT NULL;
-- The list reads an organization's places in position order, and a new place reads the
-- highest position.
CREATE INDEX saved_places_org_position ON weather.saved_places (org_id, position);
-- What place_conditions refers to: a place together with its organization.
ALTER TABLE weather.saved_places ADD CONSTRAINT saved_places_org_id_id_key UNIQUE (org_id, id);

-- The current temperature of a saved place, as Weather last looked it up, and when it did.
-- A place's row goes with the place. The foreign key names the organization as well as the
-- place: foreign key checks bypass row-level security, so with the place's id alone a row
-- could point at another organization's place.
CREATE TABLE weather.place_conditions (
    org_id bigint NOT NULL,
    place_id bigint NOT NULL,
    temperature_c numeric(5,1) NOT NULL,
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (org_id, place_id),
    FOREIGN KEY (org_id, place_id) REFERENCES weather.saved_places (org_id, id) ON DELETE CASCADE
);

ALTER TABLE weather.place_conditions ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather.place_conditions FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON weather.place_conditions
    TO ${app_role}
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);

-- Only the backend's role reads and writes the temperatures. The job role gets nothing: the
-- hourly purge never touches them, and a place's temperature goes when the place goes.
GRANT SELECT, INSERT, UPDATE, DELETE ON weather.place_conditions TO ${app_role};
