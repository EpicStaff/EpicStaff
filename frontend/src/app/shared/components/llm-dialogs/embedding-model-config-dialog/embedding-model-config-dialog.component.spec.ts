import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { EmbeddingConfig } from '@shared/models';
import {
    EmbeddingConfigStorageService,
    LLMLibraryService,
    SecretsApiService,
    SecretsStorageService,
} from '@shared/services';
import { NEVER, Observable, of, Subject, throwError } from 'rxjs';

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

/** The 400 the backend sends when a write would change where a secret goes and the caller lacks Secrets "Use". */
const SECRET_USE_REFUSAL = new HttpErrorResponse({
    status: 400,
    error: {
        status_code: 400,
        code: 'invalid',
        message:
            'extra_headers: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
            'The existing selection was left unchanged. Ask an organization admin to grant it.',
    },
});

/** The refusal as the banner shows it: the field label in words, the backend's sentence unchanged. */
const SHOWN_REFUSAL =
    'Extra headers: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
    'The existing selection was left unchanged. Ask an organization admin to grant it.';

const SERVER_ERROR = new HttpErrorResponse({
    status: 500,
    error: { status_code: 500, code: 'Exception', message: 'Unpredictable error' },
});

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

type Save = () => Observable<EmbeddingConfig>;

interface Rendered {
    fixture: ComponentFixture<EmbeddingModelConfigDialogComponent>;
    toastError: ReturnType<typeof vi.fn>;
}

/** Renders the dialog through its template; a save not given here stays in flight. */
function render(
    dialogData: { configId?: number },
    createConfig: Save = () => NEVER,
    updateConfig: Save = () => NEVER
): Rendered {
    const toastError = vi.fn();
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
            { provide: LLMLibraryService, useValue: { loadModels: () => of([]) } as unknown as LLMLibraryService },
            {
                provide: SecretsApiService,
                useValue: { getSecrets: () => of([]), getBinnedSecrets: () => of([]) } as unknown as SecretsApiService,
            },
            { provide: ToastService, useValue: { success: vi.fn(), error: toastError } as unknown as ToastService },
        ],
    });
    const fixture = TestBed.createComponent(EmbeddingModelConfigDialogComponent);
    fixture.detectChanges();
    return { fixture, toastError };
}

function fillNewConfig(fixture: ComponentFixture<EmbeddingModelConfigDialogComponent>): void {
    fixture.componentInstance.form.patchValue({ custom_name: 'new-embedder', api_key_secret_id: 4, model: 20 });
}

function save(fixture: ComponentFixture<EmbeddingModelConfigDialogComponent>): void {
    fixture.componentInstance.onSave();
    fixture.detectChanges();
}

function bannerText(fixture: ComponentFixture<EmbeddingModelConfigDialogComponent>): string {
    const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
    return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
}

describe('EmbeddingModelConfigDialogComponent save errors', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('shows the server message in the banner when saving changes fails with 400', () => {
        const { fixture, toastError } = render({ configId: EDITED_CONFIG.id }, undefined, () =>
            throwError(() => SECRET_USE_REFUSAL)
        );

        save(fixture);

        expect(bannerText(fixture)).toBe(SHOWN_REFUSAL);
        expect(toastError).not.toHaveBeenCalled();
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });

    it('shows the server message in the banner when creating fails with 400', () => {
        const { fixture } = render({}, () => throwError(() => SECRET_USE_REFUSAL));
        fillNewConfig(fixture);

        save(fixture);

        expect(bannerText(fixture)).toBe(SHOWN_REFUSAL);
    });

    it('clears the banner when the form is submitted again', () => {
        const updateConfig = vi
            .fn<Save>()
            .mockReturnValueOnce(throwError(() => SECRET_USE_REFUSAL))
            .mockReturnValueOnce(NEVER);
        const { fixture } = render({ configId: EDITED_CONFIG.id }, undefined, updateConfig);
        save(fixture);
        expect(bannerText(fixture)).not.toBe('');

        save(fixture);

        expect(bannerText(fixture)).toBe('');
    });

    it('reports a server error in a toast, not in the banner', () => {
        const { fixture, toastError } = render({ configId: EDITED_CONFIG.id }, undefined, () =>
            throwError(() => SERVER_ERROR)
        );

        save(fixture);

        expect(toastError).toHaveBeenCalledWith('Configuration update failed.');
        expect(bannerText(fixture)).toBe('');
    });
});
