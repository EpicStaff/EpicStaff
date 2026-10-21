import {
    type ApiFetch,
    describeFailure,
    type FlowRef,
    type Forecast,
    getForecastRun,
    getForecastStatus,
    MAX_CITY_LENGTH,
    startForecast,
} from './api';
import { button, element } from './dom';

export const FORECAST_PATH = '/forecast';

/** How often the page asks how the run is doing. */
export const FORECAST_POLL_INTERVAL_MS = 2_000;
/** How long the page waits for a run before it gives up. */
export const FORECAST_TIMEOUT_MS = 120_000;

export type WaitOutcome =
    | { kind: 'finished'; forecast: Forecast }
    | { kind: 'failed'; message: string }
    | { kind: 'timed-out'; lastFailure: string | null };

/**
 * Asks for the run every {@link FORECAST_POLL_INTERVAL_MS} until it finished or failed, for at most
 * {@link FORECAST_TIMEOUT_MS}. Only an unknown run (`not_found`) or the run's final status ends the wait early: any
 * other failure (the backend restarting, still being set up, EpicStaff refusing for a moment) is asked again at the
 * next poll, and the last one is reported if time runs out. `onStatus` hears every pending or running answer.
 */
export async function waitForForecast(
    fetchApi: ApiFetch,
    sessionId: number,
    pluginName: string,
    onStatus?: (status: 'pending' | 'running') => void
): Promise<WaitOutcome> {
    const deadline = Date.now() + FORECAST_TIMEOUT_MS;
    let lastFailure: string | null = null;
    while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, FORECAST_POLL_INTERVAL_MS));
        const result = await getForecastRun(fetchApi, sessionId);
        if (!result.ok) {
            if (result.code === 'not_found') {
                return {
                    kind: 'failed',
                    message: `${pluginName} no longer knows this forecast; it may have restarted. Ask for it again.`,
                };
            }
            lastFailure = describeFailure(result, pluginName);
            continue;
        }
        lastFailure = null;
        const run = result.value;
        if (run.status === 'finished') {
            return run.forecast
                ? { kind: 'finished', forecast: run.forecast }
                : { kind: 'failed', message: 'The forecast flow finished without a forecast.' };
        }
        if (run.status === 'failed') return { kind: 'failed', message: 'The forecast flow failed in EpicStaff.' };
        onStatus?.(run.status);
    }
    return { kind: 'timed-out', lastFailure };
}

type Setup =
    | { status: 'loading' }
    | { status: 'ready'; flow: FlowRef }
    | { status: 'no-flow' }
    | { status: 'unavailable'; message: string };

type Run =
    | { status: 'idle' }
    | { status: 'waiting'; city: string; progress: string }
    | { status: 'done'; forecast: Forecast }
    | { status: 'failed'; city: string; message: string };

/**
 * The Forecast page: a city, "Forecast for me", and the result of the "Weather forecast" flow EpicStaff runs on behalf
 * of the person. The form is built once and never disabled under the person's focus while a forecast runs, so a
 * re-render never takes what they typed or the focus. The result is announced politely, a failure as an alert.
 */
export class ForecastPage {
    readonly root = element('section', 'page');

    private readonly intro = element('p', 'muted');
    /** Shown while there is no flow to run: the install may still be under way. */
    private readonly checkAgainButton = button('Check again', () => this.checkSetupAgain());
    private readonly form = element('form', 'form form--inline');
    private readonly cityInput = element('input', 'input');
    private readonly submitButton = element('button', 'button', 'Forecast for me');
    private readonly result = element('div', 'result');
    private setup: Setup = { status: 'loading' };
    private run: Run = { status: 'idle' };
    /** The run the result area shows, so an unchanged run is not announced again. */
    private shownRun: Run | null = null;
    private setupRequested = false;

    constructor(
        private readonly fetchApi: ApiFetch,
        private readonly pluginName: string,
        private readonly onChange: () => void
    ) {
        const label = element('label', 'field');
        const labelText = element('span', 'field-label', 'City');
        this.cityInput.name = 'city';
        this.cityInput.required = true;
        this.cityInput.maxLength = MAX_CITY_LENGTH;
        this.cityInput.placeholder = 'Berlin';
        this.cityInput.autocomplete = 'off';
        label.append(labelText, this.cityInput);
        this.submitButton.type = 'submit';
        this.form.append(label, this.submitButton);
        this.form.addEventListener('submit', (event) => {
            event.preventDefault();
            this.requestForecast();
        });
        this.checkAgainButton.classList.add('button--secondary');
        this.result.setAttribute('aria-live', 'polite');
        this.root.append(this.intro, this.checkAgainButton, this.form, this.result);
    }

    /** Brings the page up to date; asks once which flow the install created. */
    update(): void {
        if (!this.setupRequested) {
            this.setupRequested = true;
            void this.loadSetup();
        }
        this.intro.textContent = this.introText();
        this.checkAgainButton.hidden = this.setup.status !== 'no-flow' && this.setup.status !== 'unavailable';
        const ready = this.setup.status === 'ready';
        const waiting = this.run.status === 'waiting';
        this.cityInput.disabled = !ready;
        this.submitButton.disabled = !ready;
        // Read-only rather than disabled while a forecast runs: disabling the focused field or button drops the focus.
        this.cityInput.readOnly = waiting;
        this.submitButton.setAttribute('aria-disabled', String(waiting));
        if (this.shownRun !== this.run) {
            this.shownRun = this.run;
            this.result.replaceChildren(...this.resultContent());
        }
    }

    private checkSetupAgain(): void {
        this.setup = { status: 'loading' };
        this.onChange();
        void this.loadSetup();
    }

    /** Reports through `onChange` only once it has the answer, so it may start from inside `update`. */
    private async loadSetup(): Promise<void> {
        const result = await getForecastStatus(this.fetchApi);
        if (!result.ok) this.setup = { status: 'unavailable', message: describeFailure(result, this.pluginName) };
        else this.setup = result.value ? { status: 'ready', flow: result.value } : { status: 'no-flow' };
        this.onChange();
    }

    private requestForecast(): void {
        const city = this.cityInput.value.trim();
        if (this.setup.status !== 'ready' || this.run.status === 'waiting' || city.length === 0) return;
        this.run = { status: 'waiting', city, progress: 'Starting the flow…' };
        this.onChange();
        void this.forecast(city);
    }

    /** One forecast at a time: the form ignores a new request while this runs. */
    private async forecast(city: string): Promise<void> {
        const started = await startForecast(this.fetchApi, city);
        if (!started.ok) {
            const message =
                started.code === 'invalid_request'
                    ? `Enter a city name of at most ${MAX_CITY_LENGTH} characters.`
                    : describeFailure(started, this.pluginName);
            this.finish({ status: 'failed', city, message });
            return;
        }
        const outcome = await waitForForecast(this.fetchApi, started.value, this.pluginName, (status) => {
            const progress = status === 'pending' ? 'Queued…' : 'Running…';
            if (this.run.status === 'waiting' && this.run.progress === progress) return;
            this.run = { status: 'waiting', city, progress };
            this.onChange();
        });
        switch (outcome.kind) {
            case 'finished':
                this.finish({ status: 'done', forecast: outcome.forecast });
                return;
            case 'failed':
                this.finish({ status: 'failed', city, message: outcome.message });
                return;
            case 'timed-out':
                this.finish({
                    status: 'failed',
                    city,
                    message:
                        'It took longer than 2 minutes. The run may still finish in EpicStaff; try again later.' +
                        (outcome.lastFailure ? ` The last answer was: ${outcome.lastFailure}` : ''),
                });
                return;
        }
    }

    private finish(run: Run): void {
        this.run = run;
        this.onChange();
    }

    private introText(): string {
        switch (this.setup.status) {
            case 'loading':
                return 'Looking for the forecast flow…';
            case 'ready':
                return `Runs the flow “${this.setup.flow.name}” in EpicStaff for you and shows what it found.`;
            case 'no-flow':
                return (
                    `${this.pluginName} has no forecast flow in this organization. Its install creates one; ask an ` +
                    'administrator to check the install.'
                );
            case 'unavailable':
                return this.setup.message;
        }
    }

    private resultContent(): HTMLElement[] {
        switch (this.run.status) {
            case 'idle':
                return [];
            case 'waiting':
                return [element('p', 'muted', `Forecast for ${this.run.city}: ${this.run.progress}`)];
            case 'failed': {
                const note = element('p', 'note note--error', `No forecast for ${this.run.city}. ${this.run.message}`);
                note.setAttribute('role', 'alert');
                return [note];
            }
            case 'done':
                return [forecastTable(this.run.forecast)];
        }
    }
}

/** The days of a forecast, with each day's high and low. */
function forecastTable(forecast: Forecast): HTMLElement {
    const table = element('table', 'table');
    table.append(element('caption', null, `Forecast for ${forecast.city}`));
    const head = element('thead', null);
    const headRow = element('tr', null);
    for (const title of ['Day', 'High', 'Low']) {
        const cell = element('th', null, title);
        cell.scope = 'col';
        headRow.append(cell);
    }
    head.append(headRow);
    const body = element('tbody', null);
    for (const day of forecast.days) {
        const row = element('tr', null);
        row.append(
            element('td', null, formatDay(day.date)),
            element('td', 'number', formatTemperature(day.temperature_max)),
            element('td', 'number', formatTemperature(day.temperature_min))
        );
        body.append(row);
    }
    table.append(head, body);
    return table;
}

/** `2026-10-21` as "Wed, Oct 21" in the person's language; any other text as it is. */
function formatDay(date: string): string {
    const parsed = new Date(`${date}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(parsed.getTime())) return date;
    return parsed.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
}

function formatTemperature(value: number): string {
    return `${(Math.round(value * 10) / 10).toLocaleString(undefined, { maximumFractionDigits: 1 })}°`;
}
