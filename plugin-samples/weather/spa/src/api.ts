/**
 * The Weather backend's own API, called as the signed-in person through `PluginLogin.fetch`. Every call resolves to a
 * result: the parsed answer, or the backend's error `code` the caller handles, or `unexpected` with a message to show.
 */

/** Sends a request to the plugin's own API; `PluginLogin.fetch` adds the person's token. */
export type ApiFetch = (path: string, init?: RequestInit) => Promise<Response>;

/**
 * What every route may answer: `not_installed` while the organization has no service account yet (the grant is still
 * being set up), `epicstaff_error` (with a `message`) when EpicStaff refused a call the backend made for the person.
 */
export type SharedErrorCode = 'not_installed' | 'epicstaff_error';

const SHARED_ERROR_CODES: readonly SharedErrorCode[] = ['not_installed', 'epicstaff_error'];

export type ApiFailure<Code extends string = never> = {
    ok: false;
    code: Code | SharedErrorCode | 'unexpected';
    status: number;
    message: string;
};

export type ApiResult<Value, Code extends string = never> = { ok: true; value: Value } | ApiFailure<Code>;

export interface FlowRef {
    id: number;
    name: string;
}

export interface ForecastDay {
    /** `YYYY-MM-DD`. */
    date: string;
    temperature_max: number;
    temperature_min: number;
}

export interface Forecast {
    city: string;
    days: ForecastDay[];
}

export type ForecastRunStatus = 'pending' | 'running' | 'finished' | 'failed';

export interface ForecastRun {
    status: ForecastRunStatus;
    forecast: Forecast | null;
}

export interface LlmModel {
    id: number;
    name: string;
}

export interface LlmConfigRef {
    id: number;
    name: string;
}

/** The longest city name the backend takes. */
export const MAX_CITY_LENGTH = 100;
/** The longest API key the backend takes. */
export const MAX_API_KEY_LENGTH = 4096;

const JSON_HEADERS = { 'content-type': 'application/json', accept: 'application/json' };

/** The forecast flow the install created in this organization; `null` while there is none. */
export function getForecastStatus(fetchApi: ApiFetch): Promise<ApiResult<FlowRef | null>> {
    return call(fetchApi, '/api/forecast/status', { method: 'GET' }, 200, [], (body) => {
        if (!isRecord(body) || !('flow' in body)) return undefined;
        const flow = body['flow'];
        if (flow === null) return null;
        return isIdName(flow) ? flow : undefined;
    });
}

/** Runs the forecast flow for `city` on behalf of the person; resolves to the run's session id. */
export function startForecast(fetchApi: ApiFetch, city: string): Promise<ApiResult<number, 'invalid_request'>> {
    const init = { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ city }) };
    return call(fetchApi, '/api/forecast', init, 202, ['invalid_request'], (body) =>
        isRecord(body) && isPositiveInteger(body['session_id']) ? body['session_id'] : undefined
    );
}

/** Where a run this person started stands, and its forecast once it finished. */
export function getForecastRun(fetchApi: ApiFetch, sessionId: number): Promise<ApiResult<ForecastRun, 'not_found'>> {
    return call(fetchApi, `/api/forecast/${sessionId}`, { method: 'GET' }, 200, ['not_found'], parseForecastRun);
}

/** The LLM config Weather writes its summaries with in this organization; `null` until an admin sets one up. */
export function getOrgSettings(fetchApi: ApiFetch): Promise<ApiResult<LlmConfigRef | null, 'forbidden'>> {
    return call(fetchApi, '/api/org-settings', { method: 'GET' }, 200, ['forbidden'], parseLlmConfigAnswer);
}

/** The models EpicStaff offers, to pick the summaries' model from. */
export function listLlmModels(fetchApi: ApiFetch): Promise<ApiResult<LlmModel[], 'forbidden'>> {
    return call(fetchApi, '/api/llm-models', { method: 'GET' }, 200, ['forbidden'], (body) =>
        Array.isArray(body) && body.every(isIdName) ? body : undefined
    );
}

/** Stores the key as an EpicStaff secret and creates the LLM config, on behalf of the person. */
export function saveLlmSettings(
    fetchApi: ApiFetch,
    llmModelId: number,
    apiKey: string
): Promise<ApiResult<LlmConfigRef, 'forbidden' | 'already_configured' | 'secret_exists' | 'invalid_request'>> {
    const init = {
        method: 'PUT',
        headers: JSON_HEADERS,
        body: JSON.stringify({ llm_model_id: llmModelId, api_key: apiKey }),
    };
    const codes = ['forbidden', 'already_configured', 'secret_exists', 'invalid_request'] as const;
    return call(fetchApi, '/api/org-settings/llm', init, 200, codes, (body) => {
        const config = parseLlmConfigAnswer(body);
        return config === null ? undefined : config;
    });
}

/** What to show for a failure every route may answer, or for one the caller did not expect. */
export function describeFailure(failure: ApiFailure<string>, pluginName: string): string {
    switch (failure.code) {
        case 'not_installed':
            return `${pluginName} is still being set up in this organization. Try again in a minute.`;
        case 'epicstaff_error':
            return `EpicStaff refused it: ${failure.message || 'no reason given.'}`;
        default:
            return failure.message || `The backend answered HTTP ${failure.status}.`;
    }
}

/**
 * Sends one request. `expected` is the success status; `parse` returns `undefined` for a body it does not recognise.
 * Any other status becomes the body's `code` when it is one of `codes` or a shared one, else `unexpected`.
 */
async function call<Value, Code extends string>(
    fetchApi: ApiFetch,
    path: string,
    init: RequestInit,
    expected: number,
    codes: readonly Code[],
    parse: (body: unknown) => Value | undefined
): Promise<ApiResult<Value, Code>> {
    let response: Response;
    try {
        response = await fetchApi(path, init);
    } catch (error) {
        return { ok: false, code: 'unexpected', status: 0, message: `Could not reach the backend: ${describe(error)}` };
    }
    const body = await readJson(response);
    if (response.status === expected) {
        const value = parse(body);
        if (value !== undefined) return { ok: true, value };
        return {
            ok: false,
            code: 'unexpected',
            status: response.status,
            message: 'The backend answered unexpectedly.',
        };
    }
    const code = isRecord(body) ? body['code'] : undefined;
    const message = isRecord(body) && typeof body['message'] === 'string' ? body['message'] : '';
    const known = [...codes, ...SHARED_ERROR_CODES].find((candidate) => candidate === code);
    if (known !== undefined) return { ok: false, code: known, status: response.status, message };
    return {
        ok: false,
        code: 'unexpected',
        status: response.status,
        message: `The backend answered HTTP ${response.status}.`,
    };
}

async function readJson(response: Response): Promise<unknown> {
    try {
        return await response.json();
    } catch {
        return null;
    }
}

function parseLlmConfigAnswer(body: unknown): LlmConfigRef | null | undefined {
    if (!isRecord(body) || !('llm_config' in body)) return undefined;
    const config = body['llm_config'];
    if (config === null) return null;
    return isIdName(config) ? config : undefined;
}

function parseForecastRun(body: unknown): ForecastRun | undefined {
    if (!isRecord(body)) return undefined;
    const status = body['status'];
    if (status !== 'pending' && status !== 'running' && status !== 'finished' && status !== 'failed') return undefined;
    const forecast = body['forecast'];
    if (forecast === null || forecast === undefined) return { status, forecast: null };
    return isForecast(forecast) ? { status, forecast } : undefined;
}

function isForecast(value: unknown): value is Forecast {
    return (
        isRecord(value) &&
        typeof value['city'] === 'string' &&
        Array.isArray(value['days']) &&
        value['days'].every(isForecastDay)
    );
}

function isForecastDay(value: unknown): value is ForecastDay {
    return (
        isRecord(value) &&
        typeof value['date'] === 'string' &&
        typeof value['temperature_max'] === 'number' &&
        typeof value['temperature_min'] === 'number'
    );
}

function isIdName(value: unknown): value is { id: number; name: string } {
    return isRecord(value) && isPositiveInteger(value['id']) && typeof value['name'] === 'string';
}

function isPositiveInteger(value: unknown): value is number {
    return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function describe(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}
