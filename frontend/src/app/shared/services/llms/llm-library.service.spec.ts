import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { LLMLibraryService } from './llm-library.service';

describe('LLMLibraryService', () => {
    /** Loads the configs of one type as the AI Models page does, answering only the config list. */
    function load(type: 'llm' | 'embedding', configs: object[]): LLMLibraryService {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as ConfigService },
            ],
        });
        const library = TestBed.inject(LLMLibraryService);
        const http = TestBed.inject(HttpTestingController);
        (type === 'llm' ? library.loadLlmData() : library.loadEmbeddingData()).subscribe();
        http.expectOne((request) => request.url.split('?')[0] === `/api/${type}-configs/`).flush({ results: configs });
        // No model or provider list: the configs alone name their models.
        http.verify();
        return library;
    }

    /** Each provider group's name with the config and model names of its cards. */
    function cardsByProvider(library: LLMLibraryService): Record<string, { customName: string; modelName: string }[]> {
        return Object.fromEntries(
            library
                .providerGroups()
                .map((group) => [
                    group.providerName,
                    group.models.map(({ customName, modelName }) => ({ customName, modelName })),
                ])
        );
    }

    const config = { tags: [], parameters: {}, connection: {}, needs_review: false, review_reasons: [] };

    it.each(['llm', 'embedding'] as const)(
        'shows every %s config by the provider and model it names, with no model list to look them up in',
        (type) => {
            const library = load(type, [
                {
                    ...config,
                    id: 12,
                    custom_name: 'flash',
                    model: 555,
                    provider: 'google_ai',
                    model_name: 'gemini-2.5',
                },
                { ...config, id: 13, custom_name: 'luna', model: 7, provider: 'openai', model_name: 'gpt-6-luna' },
                {
                    ...config,
                    id: 14,
                    custom_name: 'lite',
                    model: 2400,
                    provider: 'google_ai',
                    model_name: 'gemini-lite',
                },
            ]);

            expect(cardsByProvider(library)).toEqual({
                google_ai: [
                    { customName: 'flash', modelName: 'gemini-2.5' },
                    { customName: 'lite', modelName: 'gemini-lite' },
                ],
                openai: [{ customName: 'luna', modelName: 'gpt-6-luna' }],
            });
        }
    );

    it('keeps a config with no model, under an unknown provider, saying it has no model', () => {
        const library = load('llm', [
            { ...config, id: 1, custom_name: 'orphan', model: null, provider: null, model_name: null },
        ]);

        expect(cardsByProvider(library)).toEqual({ unknown: [{ customName: 'orphan', modelName: 'No model' }] });
    });

    it("takes a card's review state from the config's flag, not from whether reasons are listed", () => {
        const named = { ...config, model: 11, provider: 'openai', model_name: 'gpt-large' };
        const library = load('llm', [
            { ...named, id: 1, custom_name: 'flagged', needs_review: true, review_reasons: [] },
            { ...named, id: 2, custom_name: 'explained', needs_review: true, review_reasons: ['Model retired.'] },
            { ...named, id: 3, custom_name: 'cleared', needs_review: false, review_reasons: ['Model retired.'] },
        ]);

        expect(
            Object.fromEntries(
                library
                    .providerGroups()
                    .flatMap((group) => group.models)
                    .map((model) => [
                        model.customName,
                        { needsReview: model.needsReview, reviewReasons: model.reviewReasons },
                    ])
            )
        ).toEqual({
            flagged: { needsReview: true, reviewReasons: [] },
            explained: { needsReview: true, reviewReasons: ['Model retired.'] },
            cleared: { needsReview: false, reviewReasons: ['Model retired.'] },
        });
    });
});
