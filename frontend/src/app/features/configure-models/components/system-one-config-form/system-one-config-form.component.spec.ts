import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { GetLlmConfigRequest, SystemOneConfig } from '@shared/models';
import { LlmConfigStorageService, SecretsApiService } from '@shared/services';
import { of } from 'rxjs';

import { ConfigService } from '../../../../services/config';
import { SystemOneConfigFormComponent } from './system-one-config-form.component';

const SECRET = { id: 5, name: 'Jev key', tail: 'abcd', metadata: null, org: 1, usage_count: {} };
const LLM_CONFIG = { id: 7, custom_name: 'gpt-judge' } as GetLlmConfigRequest;
const LLM_HINT = "Its probabilities are the LLM's own estimate, not calibrated.";

const TYPESAFE_CONFIG: SystemOneConfig = {
    id: 11,
    custom_name: 'Jev prod',
    provider: 'typesafe',
    model_name: 'jev-1.13.0',
    api_key_secret_id: 5,
    llm_config: null,
    created_at: '2026-10-01T10:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function render(
    config: SystemOneConfig | null = null,
    llmConfigs: GetLlmConfigRequest[] = [LLM_CONFIG]
): {
    fixture: ComponentFixture<SystemOneConfigFormComponent>;
    http: HttpTestingController;
    saved: ReturnType<typeof vi.fn>;
} {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            {
                provide: SecretsApiService,
                useValue: { getSecrets: () => of([SECRET]), getBinnedSecrets: () => of([]) },
            },
            {
                provide: LlmConfigStorageService,
                useValue: { configs: signal(llmConfigs), getAllConfigs: () => of(llmConfigs) },
            },
        ],
    });
    const fixture = TestBed.createComponent(SystemOneConfigFormComponent);
    fixture.componentRef.setInput('config', config);
    const saved = vi.fn();
    fixture.componentInstance.saved.subscribe(saved);
    fixture.detectChanges();
    return { fixture, http: TestBed.inject(HttpTestingController), saved };
}

function host(fixture: ComponentFixture<SystemOneConfigFormComponent>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

function selectFor(fixture: ComponentFixture<SystemOneConfigFormComponent>, control: string): HTMLElement | null {
    return host(fixture).querySelector<HTMLElement>(`app-select[formcontrolname="${control}"]`);
}

function type(fixture: ComponentFixture<SystemOneConfigFormComponent>, label: string, value: string): void {
    const field = Array.from(host(fixture).querySelectorAll('app-custom-input')).find((element) =>
        element.textContent!.includes(label)
    )!;
    const input = field.querySelector('input')!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

function pick(fixture: ComponentFixture<SystemOneConfigFormComponent>, control: string, optionName: string): void {
    selectFor(fixture, control)!.querySelector<HTMLButtonElement>('.selector__btn')!.click();
    fixture.detectChanges();
    const option = Array.from(document.querySelectorAll<HTMLElement>('.selector__option')).find((element) =>
        element.textContent!.includes(optionName)
    )!;
    option.click();
    fixture.detectChanges();
}

function providerButton(fixture: ComponentFixture<SystemOneConfigFormComponent>, label: string): HTMLButtonElement {
    return Array.from(host(fixture).querySelectorAll<HTMLButtonElement>('.provider-btn')).find(
        (button) => button.textContent!.trim() === label
    )!;
}

describe('SystemOneConfigFormComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('shows the Jev version (default jev-1.14.0) and API key selects, and no LLM config select, for TypeSafe', () => {
        const { fixture } = render();

        expect(selectFor(fixture, 'model_name')!.textContent).toContain('jev-1.14.0');
        expect(selectFor(fixture, 'api_key_secret_id')).not.toBeNull();
        expect(selectFor(fixture, 'llm_config')).toBeNull();
        expect(host(fixture).textContent).not.toContain(LLM_HINT);
    });

    it('shows only the LLM config select, with its hint, after switching to LLM', () => {
        const { fixture } = render();

        providerButton(fixture, 'LLM').click();
        fixture.detectChanges();

        expect(selectFor(fixture, 'llm_config')).not.toBeNull();
        expect(selectFor(fixture, 'model_name')).toBeNull();
        expect(selectFor(fixture, 'api_key_secret_id')).toBeNull();
        expect(host(fixture).textContent).toContain(LLM_HINT);
    });

    it('tells the user to add an LLM config first when there are none to pick', () => {
        const { fixture } = render(null, []);

        providerButton(fixture, 'LLM').click();
        fixture.detectChanges();

        expect(host(fixture).textContent).toContain('No LLM configs yet.');
    });

    it('does not show that hint while LLM configs exist', () => {
        const { fixture } = render();

        providerButton(fixture, 'LLM').click();
        fixture.detectChanges();

        expect(host(fixture).textContent).not.toContain('No LLM configs yet.');
    });

    it('creates a TypeSafe config with the default Jev version and the chosen secret', () => {
        const { fixture, http, saved } = render();
        type(fixture, 'Configuration Name', 'Jev prod');
        pick(fixture, 'api_key_secret_id', 'Jev key');

        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'POST', url: '/api/system-one-configs/' });
        request.flush({ ...TYPESAFE_CONFIG, ...request.request.body });

        expect(request.request.body).toEqual({
            custom_name: 'Jev prod',
            provider: 'typesafe',
            model_name: 'jev-1.14.0',
            api_key_secret_id: 5,
            llm_config: null,
        });
        expect(saved).toHaveBeenCalledOnce();
    });

    it('creates an LLM config without a Jev version or secret', () => {
        const { fixture, http } = render();
        providerButton(fixture, 'LLM').click();
        fixture.detectChanges();
        type(fixture, 'Configuration Name', 'Judge');
        pick(fixture, 'llm_config', 'gpt-judge');

        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'POST', url: '/api/system-one-configs/' });
        request.flush({ ...TYPESAFE_CONFIG, ...request.request.body });

        expect(request.request.body).toEqual({
            custom_name: 'Judge',
            provider: 'llm',
            model_name: null,
            api_key_secret_id: null,
            llm_config: 7,
        });
    });

    it('sends nothing while the name or the provider field is empty', () => {
        const { fixture, http, saved } = render();

        fixture.componentInstance.submit();
        type(fixture, 'Configuration Name', 'Jev prod');
        fixture.componentInstance.submit();

        http.expectNone(() => true);
        expect(saved).not.toHaveBeenCalled();
    });

    it('updates an edited config with a PATCH', () => {
        const { fixture, http, saved } = render(TYPESAFE_CONFIG);
        type(fixture, 'Configuration Name', 'Jev prod EU');

        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'PATCH', url: '/api/system-one-configs/11/' });
        request.flush({ ...TYPESAFE_CONFIG, ...request.request.body });

        expect(request.request.body).toEqual({
            custom_name: 'Jev prod EU',
            provider: 'typesafe',
            model_name: 'jev-1.13.0',
            api_key_secret_id: 5,
            llm_config: null,
        });
        expect(saved).toHaveBeenCalledOnce();
    });

    it('keeps the provider of an edited config fixed', () => {
        const { fixture } = render(TYPESAFE_CONFIG);

        expect(providerButton(fixture, 'TypeSafe').disabled).toBe(false);
        expect(providerButton(fixture, 'LLM').disabled).toBe(true);
    });

    it("reports the server's message on a 400 and stays unsaved", () => {
        const { fixture, http, saved } = render(TYPESAFE_CONFIG);

        fixture.componentInstance.submit();
        http.expectOne('/api/system-one-configs/11/').flush(
            {
                status_code: 400,
                code: 'invalid',
                message: 'custom_name: A System One config with this name already exists.',
            },
            { status: 400, statusText: 'Bad Request' }
        );

        expect(fixture.componentInstance.errorMessage()).toBe(
            'custom_name: A System One config with this name already exists.'
        );
        expect(fixture.componentInstance.isSubmitting()).toBe(false);
        expect(saved).not.toHaveBeenCalled();
    });

    it('reports a generic message for a server failure', () => {
        const { fixture, http } = render(TYPESAFE_CONFIG);

        fixture.componentInstance.submit();
        http.expectOne('/api/system-one-configs/11/').flush(null, { status: 500, statusText: 'Server Error' });

        expect(fixture.componentInstance.errorMessage()).toBe('Failed to save configuration.');
    });
});
