-- Weather's tables. One database serves every organization Weather is granted to, so every
-- row carries its organization's id, and row-level security shows a session only the rows of
-- the organization `app.org_id` names. The backend sets it for each transaction
-- (epicstaff_plugin.database.org_transaction); a session that has not set it sees no rows and
-- can write none.
--
-- The node runs this file once, in one transaction, as the plugin's owner role, and replaces
-- ${app_role} with the role the backend logs in as.

CREATE SCHEMA weather;

-- The places an organization keeps; Add and Remove need Weather's Edit permission. `admin1` is
-- the region within the country, when the search knows one, so two places of one name in one
-- country (Springfield, Illinois and Springfield, Missouri) are both kept. NULLS NOT DISTINCT
-- makes a place without a region a duplicate of the same place without one.
CREATE TABLE weather.saved_places (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id bigint NOT NULL,
    name text NOT NULL,
    admin1 text,
    country text NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    created_by bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (org_id, name, admin1, country)
);

-- Which person started which forecast run, so only they can read its result.
CREATE TABLE weather.forecast_runs (
    org_id bigint NOT NULL,
    user_id bigint NOT NULL,
    session_id bigint NOT NULL,
    city text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, session_id)
);

-- What a popup posted to the relay, kept for its person until read or expired.
CREATE TABLE weather.popup_results (
    org_id bigint NOT NULL,
    user_id bigint NOT NULL,
    state text NOT NULL,
    params jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (org_id, user_id, state)
);

-- FORCE applies the policies to the tables' owner as well. An unset `app.org_id` reads as
-- NULL, which equals no organization.
ALTER TABLE weather.saved_places ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather.saved_places FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON weather.saved_places
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);

ALTER TABLE weather.forecast_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather.forecast_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON weather.forecast_runs
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);

ALTER TABLE weather.popup_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather.popup_results FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON weather.popup_results
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);

-- Only the backend's role may use the tables, and only to read and write rows.
GRANT USAGE ON SCHEMA weather TO ${app_role};
GRANT SELECT, INSERT, UPDATE, DELETE
    ON weather.saved_places, weather.forecast_runs, weather.popup_results
    TO ${app_role};
GRANT USAGE ON SEQUENCE weather.saved_places_id_seq TO ${app_role};
