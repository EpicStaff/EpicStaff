import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { EmbeddingConfig } from '@shared/models';
import { EmbeddingConfigStorageService, LlmConfigStorageService, SecretsStorageService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { AddConfigurationDialogComponent } from './add-configuration-dialog.component';

/** Class logic only: the component is built without its template. */
describe('AddConfigurationDialogComponent embedding extra headers', () => {
    let component: AddConfigurationDialogComponent;
    let createEmbeddingConfig: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        createEmbeddingConfig = vi.fn(() => of({}));

        TestBed.configureTestingModule({
            providers: [
                {
                    provide: DialogRef,
                    useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: { initialTab: 'embedding' } },
                {
                    provide: EmbeddingConfigStorageService,
                    useValue: {
                        configs: signal<EmbeddingConfig[]>([]),
                        createConfig: createEmbeddingConfig,
                    } as unknown as EmbeddingConfigStorageService,
                },
                { provide: LlmConfigStorageService, useValue: {} as LlmConfigStorageService },
                { provide: OpenAIRealtimeConfigStorageService, useValue: {} as OpenAIRealtimeConfigStorageService },
                {
                    provide: ElevenLabsRealtimeConfigStorageService,
                    useValue: {} as ElevenLabsRealtimeConfigStorageService,
                },
                { provide: GeminiRealtimeConfigStorageService, useValue: {} as GeminiRealtimeConfigStorageService },
                {
                    provide: SecretsStorageService,
                    useValue: {
                        secrets: signal([]),
                        getSecrets: () => of([]),
                        maskTail: (tail: string) => tail,
                    } as unknown as SecretsStorageService,
                },
                {
                    provide: ToastService,
                    useValue: { success: vi.fn(), error: vi.fn() } as unknown as ToastService,
                },
            ],
        });
        component = TestBed.runInInjectionContext(() => new AddConfigurationDialogComponent());
        component.ngOnInit();
    });

    it('starts the embedding form with no extra headers', () => {
        expect(component.embeddingForm.controls.extra_headers.value).toEqual({});
    });

    it('sends the extra headers when creating an embedding configuration', () => {
        component.embeddingForm.setValue({
            model: 20,
            api_key_secret_id: 4,
            custom_name: '  proxy-embedder  ',
            extra_headers: { 'X-Proxy-Key': 'epicstaff_secret(PROXY_KEY)' },
        });

        component.onSubmit();

        expect(createEmbeddingConfig).toHaveBeenCalledWith({
            model: 20,
            api_key_secret_id: 4,
            custom_name: 'proxy-embedder',
            extra_headers: { 'X-Proxy-Key': 'epicstaff_secret(PROXY_KEY)' },
        });
    });
});
