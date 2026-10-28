import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { OpenAIRealtimeConfig } from '@shared/models';
import { SecretsApiService } from '@shared/services';
import { of } from 'rxjs';

import { ConfigService } from '../../../../services/config';
import { RealtimeConfig, RealtimeConfigFormComponent, RealtimeProvider } from './realtime-config-form.component';

// Saved fields left empty come back as null; the form edits them as its defaults.
const OPENAI_CONFIG: OpenAIRealtimeConfig = {
    id: 11,
    custom_name: 'Support line',
    api_key_secret_id: 4,
    model_name: 'gpt-realtime-mini',
    base_url: null,
    transcription_model_name: null,
    transcription_api_key_secret_id: null,
    voice_recognition_prompt: 'Product names: EpicStaff',
    created_at: '2026-05-01T10:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

function render({
    config = null,
    provider = 'openai',
}: { config?: RealtimeConfig | null; provider?: RealtimeProvider } = {}): {
    fixture: ComponentFixture<RealtimeConfigFormComponent>;
    http: HttpTestingController;
    saved: ReturnType<typeof vi.fn>;
} {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            { provide: SecretsApiService, useValue: { getSecrets: () => of([]), getBinnedSecrets: () => of([]) } },
        ],
    });
    const fixture = TestBed.createComponent(RealtimeConfigFormComponent);
    fixture.componentRef.setInput('config', config);
    fixture.componentRef.setInput('provider', provider);
    const saved = vi.fn();
    fixture.componentInstance.saved.subscribe(saved);
    fixture.detectChanges();
    return { fixture, http: TestBed.inject(HttpTestingController), saved };
}

function host(fixture: ComponentFixture<RealtimeConfigFormComponent>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

function type(fixture: ComponentFixture<RealtimeConfigFormComponent>, label: string, value: string): void {
    const field = Array.from(host(fixture).querySelectorAll('app-custom-input')).find((element) =>
        element.textContent!.includes(label)
    )!;
    const input = field.querySelector('input')!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

function providerButton(fixture: ComponentFixture<RealtimeConfigFormComponent>, label: string): HTMLButtonElement {
    return Array.from(host(fixture).querySelectorAll<HTMLButtonElement>('.provider-btn')).find(
        (button) => button.textContent!.trim() === label
    )!;
}

/** jsdom has no ResizeObserver, which the overflow tooltips rendered here (as in app-select) need. */
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

describe('RealtimeConfigFormComponent', () => {
    it('asks for provider, API key, configuration name and model name, in that order', () => {
        const { fixture } = render();

        const text = host(fixture).querySelector('section')!.textContent!;
        const positions = ['Provider', 'API Key', 'Configuration Name', 'Model Name'].map((label) =>
            text.indexOf(label)
        );

        expect(positions).toEqual([...positions].sort((left, right) => left - right));
        expect(positions).not.toContain(-1);
    });

    it('creates a config for the chosen provider with its default model', () => {
        const { fixture, http, saved } = render();
        providerButton(fixture, 'Gemini').click();
        fixture.detectChanges();
        type(fixture, 'Configuration Name', 'Gemini line');

        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'POST', url: '/api/gemini-realtime-configs/' });
        request.flush({ id: 30, ...request.request.body });

        expect(request.request.body).toEqual({
            custom_name: 'Gemini line',
            api_key_secret_id: null,
            model_name: 'gemini-3.1-flash-live-preview',
            voice_recognition_prompt: '',
        });
        expect(saved).toHaveBeenCalledOnce();
    });

    it('sends nothing while the configuration name is empty', () => {
        const { fixture, http, saved } = render({ provider: 'elevenlabs' });

        fixture.componentInstance.submit();

        http.expectNone(() => true);
        expect(saved).not.toHaveBeenCalled();
    });

    it('updates an edited config, keeping the defaults for fields saved empty', () => {
        const { fixture, http, saved } = render({ config: OPENAI_CONFIG, provider: 'openai' });
        type(fixture, 'Configuration Name', 'Support line EU');

        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'PUT', url: '/api/openai-realtime-configs/11/' });
        request.flush({ ...OPENAI_CONFIG, ...request.request.body });

        expect(request.request.body).toEqual({
            id: 11,
            custom_name: 'Support line EU',
            api_key_secret_id: 4,
            model_name: 'gpt-realtime-mini',
            base_url: '',
            transcription_model_name: 'whisper-1',
            transcription_api_key_secret_id: null,
            voice_recognition_prompt: 'Product names: EpicStaff',
        });
        expect(saved).toHaveBeenCalledOnce();
    });

    it('keeps the provider of an edited config fixed', () => {
        const { fixture } = render({ config: OPENAI_CONFIG, provider: 'openai' });

        expect(providerButton(fixture, 'OpenAI').disabled).toBe(false);
        expect(providerButton(fixture, 'ElevenLabs').disabled).toBe(true);
        expect(providerButton(fixture, 'Gemini').disabled).toBe(true);
    });

    it('reports a generic error for a server failure, without emitting saved', () => {
        const { fixture, http, saved } = render({ config: OPENAI_CONFIG, provider: 'openai' });

        fixture.componentInstance.submit();
        http.expectOne('/api/openai-realtime-configs/11/').flush(
            { status_code: 500, code: 'Exception', message: 'Unpredictable error' },
            { status: 500, statusText: 'Server Error' }
        );

        expect(fixture.componentInstance.errorMessage()).toBe('Failed to save configuration.');
        expect(fixture.componentInstance.isSubmitting()).toBe(false);
        expect(saved).not.toHaveBeenCalled();
    });

    it("reports the server's reason when it refuses the save", () => {
        const reason =
            'api_key_secret_id: Changing the secrets referenced here requires the "Use" permission on Secrets.';
        const { fixture, http, saved } = render({ config: OPENAI_CONFIG, provider: 'openai' });

        fixture.componentInstance.submit();
        http.expectOne('/api/openai-realtime-configs/11/').flush(
            { status_code: 400, code: 'invalid', message: reason },
            { status: 400, statusText: 'Bad Request' }
        );

        expect(fixture.componentInstance.errorMessage()).toBe(reason);
        expect(saved).not.toHaveBeenCalled();
    });

    it('clears the reported error when a save starts again', () => {
        const { fixture, http } = render({ config: OPENAI_CONFIG, provider: 'openai' });
        fixture.componentInstance.submit();
        http.expectOne('/api/openai-realtime-configs/11/').flush(null, { status: 500, statusText: 'Server Error' });

        fixture.componentInstance.submit();

        expect(fixture.componentInstance.errorMessage()).toBeNull();
        http.expectOne('/api/openai-realtime-configs/11/');
    });
});
