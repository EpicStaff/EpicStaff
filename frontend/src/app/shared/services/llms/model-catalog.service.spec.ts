import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { CatalogModel, CatalogProvider, ModelSchemas } from '@shared/models';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ConfigService } from '../../../services/config';
import { ModelCatalogService } from './model-catalog.service';

const OPENAI: CatalogProvider = { name: 'openai', label: 'OpenAI', recommended: true, custom_models: true };

const GPT_4O: CatalogModel = {
    name: 'gpt-4o',
    recommended: true,
    deprecation_date: null,
    limits: { max_output_tokens: 16384 },
};

const GPT_4O_SCHEMAS: ModelSchemas = {
    parameters: {
        type: 'object',
        properties: {
            temperature: { type: 'number', default: 0.7, minimum: 0, maximum: 2, 'x-widget': 'slider' },
        },
        additionalProperties: false,
    },
    connection: { type: 'object', properties: {}, additionalProperties: false },
    defaults: { temperature: 0.7 },
};

describe('ModelCatalogService', () => {
    let service: ModelCatalogService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as ConfigService },
            ],
        });
        service = TestBed.inject(ModelCatalogService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => http.verify());

    it('lists the providers of a kind', () => {
        let providers: CatalogProvider[] | undefined;
        service.providers('embedding').subscribe((result) => (providers = result));

        http.expectOne('/api/ai-models/providers/?kind=embedding').flush([OPENAI]);

        expect(providers).toEqual([OPENAI]);
    });

    it('searches the models of a provider and kind', () => {
        let models: CatalogModel[] | undefined;
        service.models('llm', 'openai', 'gpt-4').subscribe((result) => (models = result));

        http.expectOne('/api/ai-models/models/?kind=llm&provider=openai&search=gpt-4').flush([GPT_4O]);

        expect(models).toEqual([GPT_4O]);
    });

    it('sends an empty search to list every model', () => {
        service.models('llm', 'openai', '').subscribe();

        http.expectOne('/api/ai-models/models/?kind=llm&provider=openai&search=').flush([]);
    });

    it('fetches the schemas of one model once, however often they are asked for', () => {
        const received: ModelSchemas[] = [];
        service.schemas('llm', 'openai', 'gpt-4o').subscribe((schemas) => received.push(schemas));
        http.expectOne('/api/ai-models/schemas/?kind=llm&provider=openai&model=gpt-4o').flush(GPT_4O_SCHEMAS);

        service.schemas('llm', 'openai', 'gpt-4o').subscribe((schemas) => received.push(schemas));

        http.expectNone(() => true);
        expect(received).toEqual([GPT_4O_SCHEMAS, GPT_4O_SCHEMAS]);
    });

    it.each([
        ['another model', ['llm', 'openai', 'gpt-4o-mini']],
        ['another provider', ['llm', 'azure', 'gpt-4o']],
        ['another kind', ['embedding', 'openai', 'gpt-4o']],
    ] as const)('fetches the schemas again for %s', (_case, [kind, provider, model]) => {
        service.schemas('llm', 'openai', 'gpt-4o').subscribe();
        http.expectOne((request) => request.url === '/api/ai-models/schemas/').flush(GPT_4O_SCHEMAS);

        service.schemas(kind, provider, model).subscribe();

        const request = http.expectOne((sent) => sent.url === '/api/ai-models/schemas/');
        expect(request.request.params.toString()).toBe(`kind=${kind}&provider=${provider}&model=${model}`);
        request.flush(GPT_4O_SCHEMAS);
    });

    it('asks again for schemas whose request failed', () => {
        const url = '/api/ai-models/schemas/?kind=llm&provider=openai&model=gpt-4o';
        service.schemas('llm', 'openai', 'gpt-4o').subscribe({ error: () => undefined });
        http.expectOne(url).flush('Server error', { status: 500, statusText: 'Server Error' });

        let schemas: ModelSchemas | undefined;
        service.schemas('llm', 'openai', 'gpt-4o').subscribe((result) => (schemas = result));
        http.expectOne(url).flush(GPT_4O_SCHEMAS);

        expect(schemas).toEqual(GPT_4O_SCHEMAS);
    });
});
