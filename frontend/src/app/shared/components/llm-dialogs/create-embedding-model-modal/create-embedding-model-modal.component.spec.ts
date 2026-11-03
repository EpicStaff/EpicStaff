import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { EmbeddingModel, LLMProvider } from '@shared/models';
import { EmbeddingModelsStorageService } from '@shared/services';
import { NEVER, Observable, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { CreateEmbeddingModelModalComponent } from './create-embedding-model-modal.component';

const PROVIDER: LLMProvider = { id: 1, name: 'openai' };

const EDITED_MODEL: EmbeddingModel = {
    id: 12,
    name: 'gateway-embedder',
    predefined: false,
    deployment: null,
    base_url: null,
    embedding_provider: PROVIDER.id,
    is_visible: true,
    is_custom: true,
};

/** The 400 the backend sends for a new base URL on a model whose configs carry a secret, without Secrets "Use". */
const SECRET_USE_REFUSAL = new HttpErrorResponse({
    status: 400,
    error: {
        status_code: 400,
        code: 'invalid',
        message:
            'base_url: Changing where this sends its secrets requires the "Use" permission on Secrets. ' +
            'The existing value was left unchanged. Ask an organization admin to grant it.',
    },
});

/** The refusal as the banner shows it: the field label in words, the backend's sentence unchanged. */
const SHOWN_REFUSAL =
    'Base URL: Changing where this sends its secrets requires the "Use" permission on Secrets. ' +
    'The existing value was left unchanged. Ask an organization admin to grant it.';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

type Save = () => Observable<EmbeddingModel>;

interface Rendered {
    fixture: ComponentFixture<CreateEmbeddingModelModalComponent>;
    toastError: ReturnType<typeof vi.fn>;
}

/** Renders the modal through its template; a save not given here stays in flight. */
function render(
    model: EmbeddingModel | undefined,
    createModel: Save = () => NEVER,
    patchModel: Save = () => NEVER
): Rendered {
    const toastError = vi.fn();
    TestBed.configureTestingModule({
        providers: [
            {
                provide: DialogRef,
                useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
            },
            { provide: DIALOG_DATA, useValue: { provider: PROVIDER, model } },
            {
                provide: EmbeddingModelsStorageService,
                useValue: { createModel, patchModel } as unknown as EmbeddingModelsStorageService,
            },
            { provide: ToastService, useValue: { error: toastError } as unknown as ToastService },
        ],
    });
    const fixture = TestBed.createComponent(CreateEmbeddingModelModalComponent);
    fixture.detectChanges();
    return { fixture, toastError };
}

function submit(fixture: ComponentFixture<CreateEmbeddingModelModalComponent>): void {
    fixture.componentInstance.onSubmit();
    fixture.detectChanges();
}

function bannerText(fixture: ComponentFixture<CreateEmbeddingModelModalComponent>): string {
    const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
    return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
}

describe('CreateEmbeddingModelModalComponent save errors', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('shows the server message in the banner when saving a new base URL fails with 400', () => {
        const { fixture, toastError } = render(EDITED_MODEL, undefined, () => throwError(() => SECRET_USE_REFUSAL));
        fixture.componentInstance.form.patchValue({ baseUrl: 'https://proxy.example.com/v1' });

        submit(fixture);

        expect(bannerText(fixture)).toBe(SHOWN_REFUSAL);
        expect(toastError).not.toHaveBeenCalled();
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });

    it('shows the server message in the banner when creating fails with 400', () => {
        const { fixture } = render(undefined, () => throwError(() => SECRET_USE_REFUSAL));
        fixture.componentInstance.form.patchValue({ name: 'custom-model' });

        submit(fixture);

        expect(bannerText(fixture)).toBe(SHOWN_REFUSAL);
    });

    it('clears the banner when the form is submitted again', () => {
        const patchModel = vi
            .fn<Save>()
            .mockReturnValueOnce(throwError(() => SECRET_USE_REFUSAL))
            .mockReturnValueOnce(NEVER);
        const { fixture } = render(EDITED_MODEL, undefined, patchModel);
        submit(fixture);
        expect(bannerText(fixture)).not.toBe('');

        submit(fixture);

        expect(bannerText(fixture)).toBe('');
    });

    it('says a built-in model cannot be edited', () => {
        const builtInRefusal = new HttpErrorResponse({
            status: 403,
            error: { status_code: 403, code: 'built_in_model_immutable', message: 'Built-in models are read-only.' },
        });
        const { fixture } = render(EDITED_MODEL, undefined, () => throwError(() => builtInRefusal));

        submit(fixture);

        expect(bannerText(fixture)).toBe('This model is a shared built-in and cannot be edited or deleted.');
    });

    it('reports a server error in a toast, not in the banner', () => {
        const serverError = new HttpErrorResponse({
            status: 500,
            error: { status_code: 500, code: 'Exception', message: 'Unpredictable error' },
        });
        const { fixture, toastError } = render(EDITED_MODEL, undefined, () => throwError(() => serverError));

        submit(fixture);

        expect(toastError).toHaveBeenCalledWith('Failed to update model.');
        expect(bannerText(fixture)).toBe('');
    });
});
