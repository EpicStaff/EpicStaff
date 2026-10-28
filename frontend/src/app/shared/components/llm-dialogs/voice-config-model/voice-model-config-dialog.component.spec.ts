import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LLMLibraryService, RealtimeConfigStorageService, SecretsApiService } from '@shared/services';
import { NEVER, Observable, of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { VoiceModelConfigDialogComponent } from './voice-model-config-dialog.component';

const EDITED_CONFIG = { id: 5, custom_name: 'support-voice', api_key_secret_id: 4, realtime_model: 9 };

/** The 400 the backend sends when a write would change where a secret goes and the caller lacks Secrets "Use". */
const SECRET_USE_REFUSAL = new HttpErrorResponse({
    status: 400,
    error: {
        status_code: 400,
        code: 'invalid',
        message:
            'api_key_secret_id: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
            'The existing selection was left unchanged. Ask an organization admin to grant it.',
    },
});

/** The refusal as the banner shows it: the field label in words, the backend's sentence unchanged. */
const SHOWN_REFUSAL =
    'API key secret: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
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

type Save = () => Observable<unknown>;

interface Rendered {
    fixture: ComponentFixture<VoiceModelConfigDialogComponent>;
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
                provide: RealtimeConfigStorageService,
                useValue: {
                    getConfigById: () => of(EDITED_CONFIG),
                    createConfig,
                    updateConfig,
                } as unknown as RealtimeConfigStorageService,
            },
            { provide: LLMLibraryService, useValue: { loadModels: () => of([]) } as unknown as LLMLibraryService },
            {
                provide: SecretsApiService,
                useValue: { getSecrets: () => of([]), getBinnedSecrets: () => of([]) } as unknown as SecretsApiService,
            },
            { provide: ToastService, useValue: { success: vi.fn(), error: toastError } as unknown as ToastService },
        ],
    });
    const fixture = TestBed.createComponent(VoiceModelConfigDialogComponent);
    fixture.detectChanges();
    return { fixture, toastError };
}

function save(fixture: ComponentFixture<VoiceModelConfigDialogComponent>): void {
    fixture.componentInstance.onSave();
    fixture.detectChanges();
}

function bannerText(fixture: ComponentFixture<VoiceModelConfigDialogComponent>): string {
    const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
    return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
}

describe('VoiceModelConfigDialogComponent save errors', () => {
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
        fixture.componentInstance.form.patchValue({ custom_name: 'new', api_key_secret_id: 4, realtime_model: 9 });

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
