import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ConfirmationDialogService } from '@shared/components';
import {
    EmbeddingConfigStorageService,
    LlmConfigStorageService,
    LlmProvidersStorageService,
    RealtimeConfigStorageService,
    TranscriptionConfigStorageService,
} from '@shared/services';
import { NEVER, Observable, of, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { GetQuickstartResponse } from '../../models/quickstart.model';
import { DefaultModelsStorageService } from '../../services/default-models-storage.service';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { QuickstartService } from '../../services/quickstart.service';
import { QuickstartSectionComponent } from './quickstart-section.component';

const STATUS: GetQuickstartResponse = { supported_providers: ['openai'], last_config: null, is_synced: false };

/** How the quickstart endpoint itself refuses: not the usual envelope, the reason sits in `error`. */
const CUSTOM_MODEL_REFUSAL = new HttpErrorResponse({
    status: 400,
    error: {
        detail: 'Error quickstart',
        error:
            'The organization\'s custom model "gpt-4o" sends requests to a custom URL, so quickstart will not ' +
            'attach a key to it.',
    },
});

/** The 400 the backend sends when the quickstart would reuse a secret the caller may not use. */
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

type QuickstartCall = () => Observable<unknown>;

interface Rendered {
    fixture: ComponentFixture<QuickstartSectionComponent>;
    toastError: ReturnType<typeof vi.fn>;
}

/** Renders the section; a quickstart call not given here stays in flight. */
function render(
    createQuickstart: QuickstartCall = () => NEVER,
    applyQuickstart: QuickstartCall = () => NEVER
): Rendered {
    const toastError = vi.fn();
    const configStorage = { getAllConfigs: () => of([]) };
    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            {
                provide: QuickstartService,
                useValue: { getQuickstart: () => of(STATUS), createQuickstart, applyQuickstart },
            },
            {
                provide: LlmProvidersStorageService,
                useValue: { getProvidersByType: () => of([{ id: 1, name: 'openai' }]) },
            },
            { provide: LlmConfigStorageService, useValue: configStorage },
            { provide: EmbeddingConfigStorageService, useValue: configStorage },
            { provide: RealtimeConfigStorageService, useValue: configStorage },
            { provide: TranscriptionConfigStorageService, useValue: configStorage },
            { provide: OpenAIRealtimeConfigStorageService, useValue: configStorage },
            { provide: GeminiRealtimeConfigStorageService, useValue: configStorage },
            { provide: ElevenLabsRealtimeConfigStorageService, useValue: configStorage },
            {
                provide: DefaultModelsStorageService,
                useValue: { markDefaultModelsOutdated: vi.fn(), updateModelsInStorage: vi.fn() },
            },
            { provide: ConfirmationDialogService, useValue: { confirm: () => of(true) } },
            { provide: PermissionsService, useValue: { canApplyQuickstart: () => true } },
            { provide: ToastService, useValue: { success: vi.fn(), error: toastError } },
        ],
    });
    const fixture = TestBed.createComponent(QuickstartSectionComponent);
    fixture.detectChanges();
    return { fixture, toastError };
}

function activate(fixture: ComponentFixture<QuickstartSectionComponent>): void {
    fixture.componentInstance.quickStartForm.setValue({ apiKey: 'sk-test', provider: 'openai' });
    fixture.componentInstance.onQuickStart();
    fixture.detectChanges();
}

function updateDefaults(fixture: ComponentFixture<QuickstartSectionComponent>): void {
    fixture.componentInstance.onUpdateDefaults();
    fixture.detectChanges();
}

function bannerText(fixture: ComponentFixture<QuickstartSectionComponent>): string {
    const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
    return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
}

describe('QuickstartSectionComponent errors', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it("shows the quickstart's own refusal in the banner", () => {
        const { fixture, toastError } = render(() => throwError(() => CUSTOM_MODEL_REFUSAL));

        activate(fixture);

        expect(bannerText(fixture)).toBe(
            'The organization\'s custom model "gpt-4o" sends requests to a custom URL, so quickstart will not ' +
                'attach a key to it.'
        );
        expect(toastError).not.toHaveBeenCalled();
    });

    it('shows a secret Use refusal in the banner, with the field label in words', () => {
        const { fixture } = render(() => throwError(() => SECRET_USE_REFUSAL));

        activate(fixture);

        expect(bannerText(fixture)).toBe(
            'API key secret: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
                'The existing selection was left unchanged. Ask an organization admin to grant it.'
        );
    });

    it('clears the banner when Activate is pressed again', () => {
        const createQuickstart = vi
            .fn<QuickstartCall>()
            .mockReturnValueOnce(throwError(() => CUSTOM_MODEL_REFUSAL))
            .mockReturnValueOnce(NEVER);
        const { fixture } = render(createQuickstart);
        activate(fixture);
        expect(bannerText(fixture)).not.toBe('');

        activate(fixture);

        expect(bannerText(fixture)).toBe('');
    });

    it('keeps the generic toast when Activate hits a server error', () => {
        const { fixture, toastError } = render(() => throwError(() => SERVER_ERROR));

        activate(fixture);

        expect(toastError).toHaveBeenCalledWith('Failed to create/apply quickstart.');
        expect(bannerText(fixture)).toBe('');
    });

    it('shows a refused update of the default models in the banner', () => {
        const { fixture } = render(undefined, () => throwError(() => SECRET_USE_REFUSAL));

        updateDefaults(fixture);

        expect(bannerText(fixture)).toContain('API key secret: Changing the secrets referenced here');
    });

    it('reports a server error while updating the default models in a toast', () => {
        const { fixture, toastError } = render(undefined, () => throwError(() => SERVER_ERROR));

        updateDefaults(fixture);

        expect(toastError).toHaveBeenCalledWith('Failed to update default models.');
        expect(bannerText(fixture)).toBe('');
    });
});
