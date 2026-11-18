import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { LLMLibraryService } from './llm-library.service';

describe('LLMLibraryService', () => {
    /** Loads the LLM configs as the AI Models page does and returns its cards' review state by config name. */
    function reviewStates(configs: object[]): Record<string, { needsReview: boolean; reviewReasons: string[] }> {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as ConfigService },
            ],
        });
        const library = TestBed.inject(LLMLibraryService);
        const http = TestBed.inject(HttpTestingController);
        library.loadLlmData().subscribe();
        const answers: Record<string, object[]> = {
            '/api/llm-configs/': configs,
            '/api/llm-models/': [{ id: 11, name: 'gpt-large', llm_provider: 1, is_visible: true, predefined: true }],
            '/api/providers/': [{ id: 1, name: 'openai' }],
        };
        for (const request of http.match(() => true)) request.flush({ results: answers[request.request.url] });

        return Object.fromEntries(
            library
                .providerGroups()
                .flatMap((group) => group.models)
                .map((model) => [
                    model.customName,
                    { needsReview: model.needsReview, reviewReasons: model.reviewReasons },
                ])
        );
    }

    it("takes a card's review state from the config's flag, not from whether reasons are listed", () => {
        const config = { model: 11, tags: [], parameters: {}, connection: {} };

        expect(
            reviewStates([
                { ...config, id: 1, custom_name: 'flagged', needs_review: true, review_reasons: [] },
                { ...config, id: 2, custom_name: 'explained', needs_review: true, review_reasons: ['Model retired.'] },
                { ...config, id: 3, custom_name: 'cleared', needs_review: false, review_reasons: ['Model retired.'] },
            ])
        ).toEqual({
            flagged: { needsReview: true, reviewReasons: [] },
            explained: { needsReview: true, reviewReasons: ['Model retired.'] },
            cleared: { needsReview: false, reviewReasons: ['Model retired.'] },
        });
    });
});
