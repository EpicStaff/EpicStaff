import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { FullLLMConfigService } from './full-llm-config.service';

describe('FullLLMConfigService', () => {
    it("names each config's model and provider from the config itself, with no model list loaded", () => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as ConfigService },
            ],
        });
        const service = TestBed.inject(FullLLMConfigService);
        const http = TestBed.inject(HttpTestingController);
        let loaded: { id: number; model: string | null; provider: string | null }[] = [];

        service.getFullLLMConfigs().subscribe(
            (configs) =>
                (loaded = configs.map((config) => ({
                    id: config.id,
                    model: config.modelDetails?.name ?? null,
                    provider: config.providerDetails?.name ?? null,
                })))
        );
        http.expectOne((request) => request.url === '/api/llm-configs/').flush({
            results: [
                { id: 12, model: 555, provider: 'google_ai', model_name: 'gemini/gemini-2.5-flash' },
                { id: 13, model: null, provider: null, model_name: null },
            ],
        });
        http.verify();

        expect(loaded).toEqual([
            { id: 12, model: 'gemini/gemini-2.5-flash', provider: 'google_ai' },
            { id: 13, model: null, provider: null },
        ]);
    });
});
