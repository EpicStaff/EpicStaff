import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ElevenLabsRealtimeConfig, GeminiRealtimeConfig, OpenAIRealtimeConfig } from '@shared/models';
import { SecretsApiService } from '@shared/services';
import { NEVER, Observable, of, Subject, throwError } from 'rxjs';

import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import {
    RealtimeConfigDialogComponent,
    RealtimeConfigDialogData,
    RealtimeProvider,
} from './realtime-config-dialog.component';

const NO_AUTHORSHIP = { created_by: null, created_at: null, last_edited_by: null, last_edited_at: null };

const OPENAI_CONFIG: OpenAIRealtimeConfig = {
    id: 1,
    custom_name: 'support-openai',
    api_key_secret_id: 4,
    model_name: 'gpt-realtime-1.5',
    base_url: null,
    transcription_model_name: 'whisper-1',
    transcription_api_key_secret_id: null,
    voice_recognition_prompt: null,
    ...NO_AUTHORSHIP,
};

const ELEVENLABS_CONFIG: ElevenLabsRealtimeConfig = {
    id: 2,
    custom_name: 'support-elevenlabs',
    api_key_secret_id: 4,
    model_name: 'eleven_turbo_v2_5',
    language: null,
    ...NO_AUTHORSHIP,
};

const GEMINI_CONFIG: GeminiRealtimeConfig = {
    id: 3,
    custom_name: 'support-gemini',
    api_key_secret_id: 4,
    model_name: 'gemini-3.1-flash-live-preview',
    voice_recognition_prompt: null,
    ...NO_AUTHORSHIP,
};

const STORED_CONFIGS = { openai: OPENAI_CONFIG, elevenlabs: ELEVENLABS_CONFIG, gemini: GEMINI_CONFIG };

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

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

type Save = () => Observable<unknown>;

interface StorageFake {
    createConfig: Save;
    updateConfig: Save;
}

/** A storage whose saves stay in flight. */
function pendingStorage(): StorageFake {
    return { createConfig: () => NEVER, updateConfig: () => NEVER };
}

/**
 * Renders the dialog for `provider`; only that provider's `action` save answers through `save`, the others stay in
 * flight, so the banner shows only when the dialog sent the save to the right storage.
 */
function render(
    provider: RealtimeProvider,
    action: RealtimeConfigDialogData['action'],
    save: Save
): ComponentFixture<RealtimeConfigDialogComponent> {
    const storages: Record<RealtimeProvider, StorageFake> = {
        openai: pendingStorage(),
        elevenlabs: pendingStorage(),
        gemini: pendingStorage(),
    };
    storages[provider][action === 'create' ? 'createConfig' : 'updateConfig'] = save;
    const data: RealtimeConfigDialogData = {
        action,
        provider,
        config: action === 'update' ? STORED_CONFIGS[provider] : null,
    };

    TestBed.configureTestingModule({
        providers: [
            {
                provide: DialogRef,
                useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
            },
            { provide: DIALOG_DATA, useValue: data },
            { provide: OpenAIRealtimeConfigStorageService, useValue: storages.openai },
            { provide: ElevenLabsRealtimeConfigStorageService, useValue: storages.elevenlabs },
            { provide: GeminiRealtimeConfigStorageService, useValue: storages.gemini },
            {
                provide: SecretsApiService,
                useValue: { getSecrets: () => of([]), getBinnedSecrets: () => of([]) } as unknown as SecretsApiService,
            },
        ],
    });
    const fixture = TestBed.createComponent(RealtimeConfigDialogComponent);
    fixture.detectChanges();
    if (action === 'create') {
        nameControl(fixture, provider).setValue('new realtime config');
    }
    return fixture;
}

function nameControl(
    fixture: ComponentFixture<RealtimeConfigDialogComponent>,
    provider: RealtimeProvider
): { setValue(value: string): void } {
    const component = fixture.componentInstance;
    const forms = { openai: component.openaiForm, elevenlabs: component.elevenLabsForm, gemini: component.geminiForm };
    return forms[provider].controls.custom_name;
}

function submit(fixture: ComponentFixture<RealtimeConfigDialogComponent>): void {
    fixture.componentInstance.onSubmit();
    fixture.detectChanges();
}

function bannerText(fixture: ComponentFixture<RealtimeConfigDialogComponent>): string {
    const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
    return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
}

describe('RealtimeConfigDialogComponent save errors', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it.each<[RealtimeProvider, RealtimeConfigDialogData['action']]>([
        ['openai', 'create'],
        ['openai', 'update'],
        ['elevenlabs', 'create'],
        ['elevenlabs', 'update'],
        ['gemini', 'create'],
        ['gemini', 'update'],
    ])('shows the server message in the banner when a %s %s fails with 400', (provider, action) => {
        const fixture = render(provider, action, () => throwError(() => SECRET_USE_REFUSAL));

        submit(fixture);

        expect(bannerText(fixture)).toBe(SHOWN_REFUSAL);
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });

    it('clears the banner when the form is submitted again', () => {
        const save = vi
            .fn<Save>()
            .mockReturnValueOnce(throwError(() => SECRET_USE_REFUSAL))
            .mockReturnValueOnce(NEVER);
        const fixture = render('openai', 'update', save);
        submit(fixture);
        expect(bannerText(fixture)).not.toBe('');

        submit(fixture);

        expect(bannerText(fixture)).toBe('');
    });

    it('keeps the generic message for a server error', () => {
        const serverError = new HttpErrorResponse({
            status: 500,
            error: { status_code: 500, code: 'Exception', message: 'Unpredictable error' },
        });
        const fixture = render('openai', 'update', () => throwError(() => serverError));

        submit(fixture);

        expect(bannerText(fixture)).toBe('Failed to save configuration.');
    });
});
