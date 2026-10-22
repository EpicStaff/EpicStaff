import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { EmbeddingConfig } from '@shared/models';
import { EmbeddingConfigStorageService, SecretsStorageService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { EmbeddingModelConfigDialogComponent } from './embedding-model-config-dialog.component';

const EDITED_CONFIG: EmbeddingConfig = {
    id: 7,
    custom_name: 'proxy-embedder',
    model: 20,
    task_type: 'retrieval_document',
    api_key_secret_id: 4,
    is_visible: true,
    extra_headers: { 'X-Proxy-Key': 'epicstaff_secret(PROXY_KEY)' },
    created_at: '2026-04-01T08:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

/** Class logic only: the component is built without its template. */
describe('EmbeddingModelConfigDialogComponent extra headers', () => {
    let createConfig: ReturnType<typeof vi.fn>;
    let updateConfig: ReturnType<typeof vi.fn>;

    function createComponent(dialogData: { configId?: number } | null): EmbeddingModelConfigDialogComponent {
        createConfig = vi.fn(() => of(EDITED_CONFIG));
        updateConfig = vi.fn(() => of(EDITED_CONFIG));

        TestBed.configureTestingModule({
            providers: [
                {
                    provide: DialogRef,
                    useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: dialogData },
                {
                    provide: EmbeddingConfigStorageService,
                    useValue: {
                        configs: signal<EmbeddingConfig[]>([]),
                        getConfigById: () => of(EDITED_CONFIG),
                        createConfig,
                        updateConfig,
                    } as unknown as EmbeddingConfigStorageService,
                },
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
        const component = TestBed.runInInjectionContext(() => new EmbeddingModelConfigDialogComponent());
        component.ngOnInit();
        return component;
    }

    it('starts a new configuration with no extra headers', () => {
        const component = createComponent(null);

        expect(component.form.get('extra_headers')?.value).toEqual({});
    });

    it('sends the extra headers when creating a configuration', () => {
        const component = createComponent(null);
        component.form.patchValue({
            custom_name: 'new-embedder',
            api_key_secret_id: 4,
            model: 20,
            extra_headers: { 'X-Team': 'search' },
        });

        component.onSave();

        expect(createConfig).toHaveBeenCalledWith(
            expect.objectContaining({ custom_name: 'new-embedder', extra_headers: { 'X-Team': 'search' } })
        );
    });

    it('prefills the extra headers of the edited configuration', () => {
        const component = createComponent({ configId: EDITED_CONFIG.id });

        expect(component.form.get('extra_headers')?.value).toEqual(EDITED_CONFIG.extra_headers);
    });

    it('sends the edited extra headers when saving changes', () => {
        const component = createComponent({ configId: EDITED_CONFIG.id });
        component.form.patchValue({ extra_headers: { 'X-Proxy-Key': 'epicstaff_secret(OTHER_KEY)' } });

        component.onSave();

        expect(updateConfig).toHaveBeenCalledWith(
            expect.objectContaining({
                id: EDITED_CONFIG.id,
                extra_headers: { 'X-Proxy-Key': 'epicstaff_secret(OTHER_KEY)' },
            })
        );
    });
});
