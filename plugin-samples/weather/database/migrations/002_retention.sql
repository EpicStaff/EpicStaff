-- How long Weather keeps what it keeps only for a while: a forecast run for 7 days, a popup
-- result until it expires. Once an hour the backend deletes older rows of every organization
-- as the plugin's job role (weather_plugin.retention, through
-- epicstaff_plugin.database.job_transaction), in batches. Requests delete nothing old, and
-- never hand out an expired popup result.
--
-- The job role may read only the timestamps of expired rows, and delete only expired rows: the
-- retention rule is in the policies below, so no code can widen it.

-- The organization policies are for the app role alone. A job transaction sets no
-- organization, and must never reach a live row through them.
ALTER POLICY org_rows ON weather.saved_places TO ${app_role};
ALTER POLICY org_rows ON weather.forecast_runs TO ${app_role};
ALTER POLICY org_rows ON weather.popup_results TO ${app_role};

-- The purge walks each table in timestamp order, across organizations.
CREATE INDEX forecast_runs_created_at ON weather.forecast_runs (created_at);
CREATE INDEX popup_results_expires_at ON weather.popup_results (expires_at);

-- A DELETE whose WHERE reads a column needs SELECT on it, and the SELECT policies apply too.
CREATE POLICY expired_rows_read ON weather.forecast_runs
    FOR SELECT TO ${job_role}
    USING (created_at < now() - interval '7 days');
CREATE POLICY expired_rows_delete ON weather.forecast_runs
    FOR DELETE TO ${job_role}
    USING (created_at < now() - interval '7 days');

CREATE POLICY expired_rows_read ON weather.popup_results
    FOR SELECT TO ${job_role}
    USING (expires_at <= now());
CREATE POLICY expired_rows_delete ON weather.popup_results
    FOR DELETE TO ${job_role}
    USING (expires_at <= now());

GRANT USAGE ON SCHEMA weather TO ${job_role};
GRANT SELECT (created_at), DELETE ON weather.forecast_runs TO ${job_role};
GRANT SELECT (expires_at), DELETE ON weather.popup_results TO ${job_role};
