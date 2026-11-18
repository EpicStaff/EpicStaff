import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
    CatalogModel,
    CatalogProvider,
    EmbeddingConfig,
    GetLlmConfigRequest,
    ModelSchemas,
    Secret,
} from '@shared/models';
import { SecretsApiService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { ModelConfigDialogComponent, ModelConfigDialogData } from './model-config-dialog.component';

const OPENAI: CatalogProvider = { name: 'openai', label: 'OpenAI', recommended: true, custom_models: true };

const LARGE_MODEL: CatalogModel = {
    name: 'gpt-large',
    recommended: true,
    deprecation_date: null,
    limits: { max_output_tokens: 16384 },
    custom: false,
};
const SMALL_MODEL: CatalogModel = {
    name: 'gpt-small',
    recommended: false,
    deprecation_date: null,
    limits: { max_output_tokens: 8192 },
    custom: false,
};
/** The organization's own model, saved earlier under a typed name. */
const TEAM_MODEL: CatalogModel = {
    name: 'team-finetune',
    recommended: false,
    deprecation_date: null,
    limits: {},
    custom: true,
};

const OTHER: CatalogProvider = { name: 'other', label: 'Other', recommended: false, custom_models: false };
const PROD_KEY = { id: 3, name: 'prod-key', tail: 'abcd' } as Secret;

const NO_CONNECTION: ModelSchemas['connection'] = { type: 'object', properties: {}, additionalProperties: false };

/** Takes `seed`, and up to 16384 output tokens. */
const LARGE_SCHEMAS: ModelSchemas = {
    parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
            temperature: {
                type: 'number',
                title: 'Temperature',
                default: 0.7,
                minimum: 0,
                maximum: 2,
                'x-step': 0.01,
                'x-widget': 'slider',
            },
            max_tokens: {
                type: 'integer',
                title: 'Max tokens',
                default: 4096,
                minimum: 1,
                maximum: 16384,
                'x-widget': 'stepper',
            },
            seed: { type: ['integer', 'null'], title: 'Seed', default: null, 'x-widget': 'stepper' },
        },
    },
    connection: NO_CONNECTION,
    defaults: { temperature: 0.7, max_tokens: 4096 },
};

/** No `seed`, at most 8192 output tokens, and a reasoning effort. */
const SMALL_SCHEMAS: ModelSchemas = {
    parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
            temperature: LARGE_SCHEMAS.parameters.properties['temperature'],
            max_tokens: { ...LARGE_SCHEMAS.parameters.properties['max_tokens'], maximum: 8192 },
            reasoning_effort: {
                type: 'string',
                title: 'Reasoning effort',
                default: 'medium',
                enum: ['low', 'medium', 'high'],
                'x-widget': 'select',
            },
        },
    },
    connection: NO_CONNECTION,
    defaults: { temperature: 0.7, max_tokens: 4096, reasoning_effort: 'medium' },
};

/** The large model behind a proxy: a base URL and a secret, both optional. */
const PROXY_SCHEMAS: ModelSchemas = {
    ...LARGE_SCHEMAS,
    connection: {
        type: 'object',
        additionalProperties: false,
        properties: {
            base_url: { type: 'string', title: 'Base URL', 'x-widget': 'text' },
            aws_access_key_id: { type: 'string', title: 'AWS access key ID', 'x-widget': 'secret' },
        },
    },
};

const STORED_CONFIG: GetLlmConfigRequest = {
    id: 3,
    custom_name: 'support assistant',
    model: 11,
    provider: 'openai',
    model_name: 'gpt-large',
    api_key_secret_id: null,
    parameters: { temperature: 0.2, max_tokens: 10000, seed: 42 },
    connection: {},
    needs_review: false,
    review_reasons: [],
    timeout: 120,
    is_visible: true,
    extra_headers: {},
    input_cost_per_token: null,
    output_cost_per_token: null,
    tags: [],
    created_at: null,
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

/** The fields the catalog replaced; no write may carry them any more. */
const FLAT_FIELDS = ['temperature', 'top_p', 'max_tokens', 'seed', 'reasoning_effort', 'base_url', 'api_version'];

// The dialog's buttons collapse on overflow and observe their size; jsdom has no ResizeObserver.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

interface Rendered {
    fixture: ComponentFixture<ModelConfigDialogComponent>;
    http: HttpTestingController;
}

function render(data: ModelConfigDialogData, secrets: Secret[] = []): Rendered {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/' } as ConfigService },
            { provide: DIALOG_DATA, useValue: data },
            {
                provide: DialogRef,
                useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
            },
            {
                provide: SecretsApiService,
                useValue: {
                    getSecrets: () => of(secrets),
                    getBinnedSecrets: () => of([]),
                } as unknown as SecretsApiService,
            },
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } as unknown as ToastService },
        ],
    });
    const fixture = TestBed.createComponent(ModelConfigDialogComponent);
    fixture.detectChanges();
    return { fixture, http: TestBed.inject(HttpTestingController) };
}

function answer(rendered: Rendered, url: string, body: object, params: Record<string, string> = {}): TestRequest {
    const request = rendered.http.expectOne(
        (candidate) =>
            candidate.url === url &&
            Object.entries(params).every(([name, value]) => candidate.params.get(name) === value)
    );
    request.flush(body);
    rendered.fixture.detectChanges();
    return request;
}

/** Opens the catalog with the large model's config, as the edit button does. */
function renderEdit(config: GetLlmConfigRequest = STORED_CONFIG, schemas: ModelSchemas = LARGE_SCHEMAS): Rendered {
    const rendered = render({ kind: 'llm', configId: config.id });
    answer(rendered, '/api/ai-models/providers/', [OPENAI]);
    answer(rendered, '/api/llm-configs/3/', config);
    answer(rendered, '/api/ai-models/models/', [LARGE_MODEL, SMALL_MODEL], { provider: 'openai' });
    answer(rendered, '/api/ai-models/schemas/', schemas, { model: 'gpt-large' });
    return rendered;
}

/** A new LLM config named, with OpenAI chosen and its models listed. */
function renderCreate(secrets: Secret[] = []): Rendered {
    const rendered = render({ kind: 'llm' }, secrets);
    answer(rendered, '/api/ai-models/providers/', [OPENAI, OTHER]);
    typeName(rendered.fixture, 'support assistant');
    choose(rendered.fixture, '.dialog__provider', 'OpenAI');
    answer(rendered, '/api/ai-models/models/', [LARGE_MODEL], { provider: 'openai', search: '' });
    return rendered;
}

function typeName(fixture: ComponentFixture<ModelConfigDialogComponent>, text: string): void {
    const name = element(fixture).querySelector<HTMLInputElement>('app-custom-input input')!;
    name.value = text;
    name.dispatchEvent(new Event('input'));
}

/** The model's schemas come from the network once; a model chosen again is answered from the catalog's cache. */
function answerSchemasIfAsked(rendered: Rendered, model: string, schemas: ModelSchemas): void {
    rendered.http
        .match((candidate) => candidate.url === '/api/ai-models/schemas/' && candidate.params.get('model') === model)
        .forEach((request) => request.flush(schemas));
    rendered.fixture.detectChanges();
}

function refuse(rendered: Rendered, url: string, errors: { field: string; reason: string }[]): void {
    saveButton(rendered.fixture).click();
    rendered.http.expectOne(url).flush({ errors }, { status: 400, statusText: 'Bad Request' });
    rendered.fixture.detectChanges();
}

function banner(fixture: ComponentFixture<ModelConfigDialogComponent>): string {
    return element(fixture).querySelector('app-error-banner')!.textContent!.trim();
}

function element(fixture: ComponentFixture<ModelConfigDialogComponent>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

/** Picks `option` in the select inside `selector`, as a click on it and then on the option does. */
function choose(fixture: ComponentFixture<ModelConfigDialogComponent>, selector: string, option: string): void {
    element(fixture).querySelector<HTMLButtonElement>(`${selector} .selector__btn`)!.click();
    fixture.detectChanges();
    Array.from(document.querySelectorAll<HTMLButtonElement>('.selector__option'))
        .find((button) => button.querySelector('.selector__text')?.textContent?.trim() === option)!
        .click();
    fixture.detectChanges();
}

function changeList(fixture: ComponentFixture<ModelConfigDialogComponent>): string[] {
    return Array.from(element(fixture).querySelectorAll('.dialog__change-list li'), (item) => item.textContent!.trim());
}

function buttonLabelled(fixture: ComponentFixture<ModelConfigDialogComponent>, label: string): HTMLButtonElement {
    return Array.from(element(fixture).querySelectorAll<HTMLButtonElement>('app-button button')).find(
        (button) => button.textContent?.trim() === label
    )!;
}

/** The dialog's primary action: "Add LLM", "Add Embedding" or "Save Changes". */
function saveButton(fixture: ComponentFixture<ModelConfigDialogComponent>): HTMLButtonElement {
    return Array.from(element(fixture).querySelectorAll<HTMLButtonElement>('.dialog__footer app-button button')).at(
        -1
    )!;
}

function save(rendered: Rendered, url: string, method: 'POST' | 'PUT'): Record<string, unknown> {
    saveButton(rendered.fixture).click();
    const request = rendered.http.expectOne((candidate) => candidate.url === url && candidate.method === method);
    return request.request.body as Record<string, unknown>;
}

describe('ModelConfigDialogComponent', () => {
    it('lists the embedding providers for an embedding config', () => {
        const rendered = render({ kind: 'embedding' });

        answer(rendered, '/api/ai-models/providers/', [{ ...OPENAI, label: 'OpenAI Embeddings' }], {
            kind: 'embedding',
        });
        element(rendered.fixture).querySelector<HTMLButtonElement>('.dialog__provider .selector__btn')!.click();
        rendered.fixture.detectChanges();

        expect(
            Array.from(document.querySelectorAll('.selector__option .selector__text'), (text) =>
                text.textContent!.trim()
            )
        ).toEqual(['OpenAI Embeddings']);
        rendered.http.verify();
    });

    it('fits the settings to a newly chosen model and lists every change', () => {
        const rendered = renderEdit();

        choose(rendered.fixture, '.dialog__model', 'gpt-small');
        answer(rendered, '/api/ai-models/schemas/', SMALL_SCHEMAS, { model: 'gpt-small' });

        expect(changeList(rendered.fixture)).toEqual([
            'Max tokens: 10000 → 8192',
            'Seed: removed, the new model does not support it',
            'Reasoning effort: added, set to Medium',
        ]);
        const body = save(rendered, '/api/llm-configs/3/', 'PUT');
        expect(body['parameters']).toEqual({ temperature: 0.2, max_tokens: 8192, reasoning_effort: 'medium' });
    });

    it('puts every setting back to its default with "Set defaults"', () => {
        const rendered = renderEdit();

        buttonLabelled(rendered.fixture, 'Set defaults').click();
        rendered.fixture.detectChanges();

        const body = save(rendered, '/api/llm-configs/3/', 'PUT');
        expect(body['parameters']).toEqual({ temperature: 0.7, max_tokens: 4096 });
    });

    it('saves an unchanged model by its id', () => {
        const rendered = renderEdit();

        const body = save(rendered, '/api/llm-configs/3/', 'PUT');

        expect(body).toEqual(expect.objectContaining({ id: 3, model: 11, custom_name: 'support assistant' }));
        expect(body).not.toHaveProperty('provider');
    });

    it('creates a config from the provider, the model name, its settings and its connection, with no flat fields', () => {
        const rendered = render({ kind: 'llm' });
        answer(rendered, '/api/ai-models/providers/', [OPENAI]);
        const name = element(rendered.fixture).querySelector<HTMLInputElement>('app-custom-input input')!;
        name.value = 'support assistant';
        name.dispatchEvent(new Event('input'));

        choose(rendered.fixture, '.dialog__provider', 'OpenAI');
        answer(rendered, '/api/ai-models/models/', [LARGE_MODEL], { provider: 'openai', search: '' });
        choose(rendered.fixture, '.dialog__model', 'gpt-large');
        answer(rendered, '/api/ai-models/schemas/', LARGE_SCHEMAS, { model: 'gpt-large' });

        const body = save(rendered, '/api/llm-configs/', 'POST');
        expect(body).toEqual(
            expect.objectContaining({
                provider: 'openai',
                model_name: 'gpt-large',
                parameters: { temperature: 0.7, max_tokens: 4096 },
                connection: {},
            })
        );
        expect(body).not.toHaveProperty('model');
        for (const field of FLAT_FIELDS) expect(body).not.toHaveProperty(field);
        expect(changeList(rendered.fixture)).toEqual([]);
    });

    it("shows the server's refusal of a setting under that setting", () => {
        const rendered = renderEdit();
        buttonLabelled(rendered.fixture, 'Save Changes').click();

        rendered.http
            .expectOne('/api/llm-configs/3/')
            .flush(
                { errors: [{ field: 'parameters.max_tokens', reason: 'Must be at most 16384.' }] },
                { status: 400, statusText: 'Bad Request' }
            );
        rendered.fixture.detectChanges();

        expect(element(rendered.fixture).querySelector('[data-field="max_tokens"]')!.textContent).toContain(
            'Must be at most 16384.'
        );
        expect(element(rendered.fixture).querySelector('app-error-banner')!.textContent!.trim()).toBe('');
    });

    describe('a stored config opened for editing', () => {
        it('shows the provider and the model the config names itself, without looking its model up', () => {
            const rendered = renderEdit();

            expect(element(rendered.fixture).querySelector('.dialog__provider .selector__btn')!.textContent).toContain(
                'OpenAI'
            );
            expect(element(rendered.fixture).querySelector('.dialog__model .selector__btn')!.textContent).toContain(
                'gpt-large'
            );
            rendered.http.expectNone(
                (candidate) => candidate.url.startsWith('/api/llm-models/') || candidate.url === '/api/providers/'
            );
        });

        it('is fitted to its own model, lists what that changed, and saves without the unsupported setting', () => {
            const schemas: ModelSchemas = {
                ...LARGE_SCHEMAS,
                parameters: {
                    ...LARGE_SCHEMAS.parameters,
                    properties: {
                        ...LARGE_SCHEMAS.parameters.properties,
                        top_p: {
                            type: 'number',
                            title: 'Top P',
                            default: 0.9,
                            minimum: 0.01,
                            maximum: 0.9,
                            'x-scale': 100,
                            'x-widget': 'percent',
                        },
                    },
                },
            };
            const rendered = renderEdit(
                {
                    ...STORED_CONFIG,
                    parameters: { temperature: 0.2, max_tokens: 20000, top_p: 1, frequency_penalty: 0.5 },
                },
                schemas
            );

            const note = element(rendered.fixture).querySelector('.dialog__changes')!;
            expect(note.getAttribute('role')).toBe('status');
            expect(note.textContent).toContain('The stored configuration was changed to fit the model');
            expect(changeList(rendered.fixture)).toEqual([
                'Max tokens: 20000 → 16384',
                'Top P: 100% → 90%',
                'frequency_penalty: removed, the model does not support it',
            ]);
            const body = save(rendered, '/api/llm-configs/3/', 'PUT');
            expect(body['parameters']).toEqual({ temperature: 0.2, max_tokens: 16384, top_p: 0.9 });
        });

        it('resends a stored connection field the model does not list, unchanged and without showing it', () => {
            const rendered = renderEdit(
                { ...STORED_CONFIG, connection: { base_url: 'https://proxy.example.com', region: 'eu' } },
                PROXY_SCHEMAS
            );

            expect(element(rendered.fixture).querySelector('[data-field="region"]')).toBeNull();
            expect(changeList(rendered.fixture)).toEqual([]);
            const body = save(rendered, '/api/llm-configs/3/', 'PUT');
            expect(body['connection']).toEqual({ base_url: 'https://proxy.example.com', region: 'eu' });
        });

        it('drops that connection field with a model switch, and lists it', () => {
            const rendered = renderEdit({ ...STORED_CONFIG, connection: { region: 'eu' } }, PROXY_SCHEMAS);

            choose(rendered.fixture, '.dialog__model', 'gpt-small');
            answer(rendered, '/api/ai-models/schemas/', SMALL_SCHEMAS, { model: 'gpt-small' });

            expect(changeList(rendered.fixture)).toContain(
                'region: connection field removed, the new model does not use it'
            );
            const body = save(rendered, '/api/llm-configs/3/', 'PUT');
            expect(body['connection']).toEqual({});
        });

        it('shows why the config needs review', () => {
            const rendered = renderEdit({
                ...STORED_CONFIG,
                needs_review: true,
                review_reasons: ['The model left the catalog.'],
            });

            expect(element(rendered.fixture).querySelector('.dialog__review')!.textContent).toContain(
                'The model left the catalog.'
            );
        });

        it('shows no review note for a config that needs none', () => {
            const rendered = renderEdit();

            expect(element(rendered.fixture).querySelector('.dialog__review')).toBeNull();
        });

        it('closes with an error instead of leaving an empty form when the config cannot be loaded', () => {
            const rendered = render({ kind: 'llm', configId: STORED_CONFIG.id });
            answer(rendered, '/api/ai-models/providers/', [OPENAI]);

            rendered.http
                .expectOne('/api/llm-configs/3/')
                .flush('unavailable', { status: 500, statusText: 'Server Error' });
            rendered.fixture.detectChanges();

            expect(TestBed.inject(DialogRef).close).toHaveBeenCalled();
            expect(TestBed.inject(ToastService).error).toHaveBeenCalledWith('Failed to load configuration.');
            expect(element(rendered.fixture).querySelector('.dialog__body')).toBeNull();
        });

        it('shows no form until the config has arrived', () => {
            const rendered = render({ kind: 'llm', configId: STORED_CONFIG.id });

            expect(element(rendered.fixture).querySelector('.dialog__body')).toBeNull();
        });
    });

    describe('a model switch', () => {
        it('sends the changed model of an edited config as its provider and name', () => {
            const rendered = renderEdit();

            choose(rendered.fixture, '.dialog__model', 'gpt-small');
            answer(rendered, '/api/ai-models/schemas/', SMALL_SCHEMAS, { model: 'gpt-small' });

            const body = save(rendered, '/api/llm-configs/3/', 'PUT');
            expect(body).toEqual(expect.objectContaining({ id: 3, provider: 'openai', model_name: 'gpt-small' }));
            expect(body).not.toHaveProperty('model');
        });

        it('lists only the last switch after switching away and back, and saves the own model by its id', () => {
            const rendered = renderEdit();

            choose(rendered.fixture, '.dialog__model', 'gpt-small');
            answer(rendered, '/api/ai-models/schemas/', SMALL_SCHEMAS, { model: 'gpt-small' });
            choose(rendered.fixture, '.dialog__model', 'gpt-large');
            answerSchemasIfAsked(rendered, 'gpt-large', LARGE_SCHEMAS);

            expect(changeList(rendered.fixture)).toEqual([
                'Reasoning effort: removed, the new model does not support it',
            ]);
            const body = save(rendered, '/api/llm-configs/3/', 'PUT');
            expect(body['parameters']).toEqual({ temperature: 0.2, max_tokens: 8192 });
            expect(body['model']).toBe(11);
        });

        it("offers the organization's own models first, tagged Custom", () => {
            const rendered = render({ kind: 'llm' });
            answer(rendered, '/api/ai-models/providers/', [OPENAI, OTHER]);
            choose(rendered.fixture, '.dialog__provider', 'OpenAI');
            answer(rendered, '/api/ai-models/models/', [TEAM_MODEL, LARGE_MODEL], { provider: 'openai', search: '' });

            element(rendered.fixture).querySelector<HTMLButtonElement>('.dialog__model .selector__btn')!.click();
            rendered.fixture.detectChanges();
            const options = Array.from(document.querySelectorAll('.selector__option'), (option) => ({
                name: option.querySelector('.selector__text')?.textContent?.trim(),
                tip: option.querySelector('.selector__tip')?.textContent?.trim(),
            }));

            expect(options).toEqual([
                { name: 'team-finetune', tip: 'Custom' },
                { name: 'gpt-large', tip: 'Recommended' },
            ]);
        });

        it('saves a model name typed into the search of a provider that takes custom models', () => {
            const rendered = renderCreate();
            element(rendered.fixture).querySelector<HTMLButtonElement>('.dialog__model .selector__btn')!.click();
            rendered.fixture.detectChanges();
            const search = document.querySelector<HTMLInputElement>('.selector__search')!;
            search.value = 'my-finetune';
            search.dispatchEvent(new Event('input'));
            rendered.fixture.detectChanges();

            Array.from(document.querySelectorAll<HTMLButtonElement>('.selector__option'))
                .find((option) => option.textContent?.trim() === 'Use "my-finetune"')!
                .click();
            rendered.fixture.detectChanges();
            answer(rendered, '/api/ai-models/schemas/', LARGE_SCHEMAS, { model: 'my-finetune' });

            const body = save(rendered, '/api/llm-configs/', 'POST');
            expect(body).toEqual(expect.objectContaining({ provider: 'openai', model_name: 'my-finetune' }));
        });

        it("drops a model's settings still on their way when the provider changes", () => {
            const rendered = renderCreate();
            choose(rendered.fixture, '.dialog__model', 'gpt-large');
            const pending = rendered.http.expectOne((candidate) => candidate.url === '/api/ai-models/schemas/');

            choose(rendered.fixture, '.dialog__provider', 'Other');
            if (!pending.cancelled) pending.flush(LARGE_SCHEMAS);
            rendered.fixture.detectChanges();

            expect(element(rendered.fixture).querySelector('app-schema-form')).toBeNull();
            expect(element(rendered.fixture).querySelector('.dialog__model .selector__btn')!.textContent).toContain(
                'Select a model'
            );
        });
    });

    it('sends a picked secret connection field as its marker', () => {
        const rendered = renderCreate([PROD_KEY]);
        choose(rendered.fixture, '.dialog__model', 'gpt-large');
        answer(rendered, '/api/ai-models/schemas/', PROXY_SCHEMAS, { model: 'gpt-large' });

        choose(rendered.fixture, '[data-field="aws_access_key_id"]', 'prod-key');

        const body = save(rendered, '/api/llm-configs/', 'POST');
        expect(body['connection']).toEqual({ aws_access_key_id: 'epicstaff_secret(prod-key)' });
    });

    describe('a refused save', () => {
        it('says an error for a field that is not on screen, and one for another field, in the banner', () => {
            const rendered = renderEdit();

            refuse(rendered, '/api/llm-configs/3/', [
                { field: 'parameters.max_tokens', reason: 'Must be at most 16384.' },
                { field: 'parameters.top_k', reason: 'Not a setting of this model.' },
                { field: 'custom_name', reason: 'Already taken.' },
            ]);

            expect(element(rendered.fixture).querySelector('[data-field="max_tokens"]')!.textContent).toContain(
                'Must be at most 16384.'
            );
            expect(banner(rendered.fixture)).toContain('Not a setting of this model.');
            expect(banner(rendered.fixture)).toContain('Already taken.');
            expect(banner(rendered.fixture)).not.toContain('Must be at most 16384.');
        });

        it("clears a setting's error once that setting is edited, and keeps the others", () => {
            const rendered = renderEdit();
            refuse(rendered, '/api/llm-configs/3/', [
                { field: 'parameters.max_tokens', reason: 'Must be at most 16384.' },
                { field: 'parameters.temperature', reason: 'Too hot.' },
            ]);

            const maxTokens = element(rendered.fixture).querySelector<HTMLInputElement>(
                '[data-field="max_tokens"] .number-stepper__input'
            )!;
            maxTokens.value = '8000';
            maxTokens.dispatchEvent(new Event('input'));
            maxTokens.dispatchEvent(new Event('blur'));
            rendered.fixture.detectChanges();

            expect(element(rendered.fixture).querySelector('[data-field="max_tokens"]')!.textContent).not.toContain(
                'Must be at most 16384.'
            );
            expect(element(rendered.fixture).querySelector('[data-field="temperature"]')!.textContent).toContain(
                'Too hot.'
            );
        });
    });

    describe('an embedding config', () => {
        const EMBEDDING_SCHEMAS: ModelSchemas = {
            parameters: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    dimensions: {
                        type: 'integer',
                        title: 'Dimensions',
                        default: 1536,
                        minimum: 1,
                        maximum: 3072,
                        'x-widget': 'stepper',
                    },
                },
            },
            connection: NO_CONNECTION,
            defaults: { dimensions: 1536 },
        };
        const STORED_EMBEDDING: EmbeddingConfig = {
            id: 5,
            custom_name: 'search index',
            model: 21,
            provider: 'openai',
            model_name: 'embed-large',
            api_key_secret_id: 3,
            is_visible: true,
            extra_headers: {},
            parameters: { dimensions: 256 },
            connection: {},
            needs_review: false,
            review_reasons: [],
            created_at: null,
            created_by: null,
            last_edited_by: null,
            last_edited_at: null,
        };

        it('is created with its API key and the settings of its model, and no LLM-only fields', () => {
            const rendered = render({ kind: 'embedding' }, [PROD_KEY]);
            answer(rendered, '/api/ai-models/providers/', [OPENAI], { kind: 'embedding' });
            typeName(rendered.fixture, 'search index');
            choose(rendered.fixture, '.dialog__provider', 'OpenAI');
            answer(rendered, '/api/ai-models/models/', [{ ...LARGE_MODEL, name: 'embed-large' }]);
            choose(rendered.fixture, '.dialog__model', 'embed-large');
            answer(rendered, '/api/ai-models/schemas/', EMBEDDING_SCHEMAS, { kind: 'embedding' });
            choose(rendered.fixture, '[formcontrolname="api_key_secret_id"]', 'prod-key');

            const body = save(rendered, '/api/embedding-configs/', 'POST');

            expect(body).toEqual(
                expect.objectContaining({
                    custom_name: 'search index',
                    provider: 'openai',
                    model_name: 'embed-large',
                    api_key_secret_id: 3,
                    parameters: { dimensions: 1536 },
                })
            );
            for (const field of ['timeout', 'input_cost_per_token', 'output_cost_per_token']) {
                expect(body).not.toHaveProperty(field);
            }
        });

        it('is edited with its stored settings and saved by its model id', () => {
            const rendered = render({ kind: 'embedding', configId: 5 }, [PROD_KEY]);
            answer(rendered, '/api/ai-models/providers/', [OPENAI], { kind: 'embedding' });
            answer(rendered, '/api/embedding-configs/5/', STORED_EMBEDDING);
            answer(rendered, '/api/ai-models/models/', [], { provider: 'openai' });
            answer(rendered, '/api/ai-models/schemas/', EMBEDDING_SCHEMAS, { model: 'embed-large' });

            const body = save(rendered, '/api/embedding-configs/5/', 'PUT');

            expect(body).toEqual(
                expect.objectContaining({
                    id: 5,
                    model: 21,
                    custom_name: 'search index',
                    api_key_secret_id: 3,
                    parameters: { dimensions: 256 },
                })
            );
        });
    });
});
