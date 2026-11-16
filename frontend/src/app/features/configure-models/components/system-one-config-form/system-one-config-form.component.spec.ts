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

const OPENAI_CONFIG: SystemOneConfig = {
    ...TYPESAFE_CONFIG,
    id: 12,
    custom_name: 'OpenAI prod',
    provider: 'openai',
    model_name: 'gpt-6-luna',
};

const OTHER_LLM_CONFIG = { id: 8, custom_name: 'claude-judge' } as GetLlmConfigRequest;
const LLM_EDIT_CONFIG: SystemOneConfig = {
    ...TYPESAFE_CONFIG,
    id: 13,
    custom_name: 'Judge',
    provider: 'llm',
    model_name: null,
    api_key_secret_id: null,
    llm_config: 7,
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

function pickerTrigger(fixture: ComponentFixture<SystemOneConfigFormComponent>): HTMLButtonElement {
    return host(fixture).querySelector<HTMLButtonElement>('app-grouped-picker button[aria-expanded]')!;
}

function pickerField(fixture: ComponentFixture<SystemOneConfigFormComponent>): HTMLElement {
    return host(fixture).querySelector('app-grouped-picker')!.parentElement!;
}

/** The text of the open picker: its group names (upper-cased) and items. */
function openPicker(fixture: ComponentFixture<SystemOneConfigFormComponent>): string {
    pickerTrigger(fixture).click();
    fixture.detectChanges();
    return document.querySelector('.cdk-overlay-container')!.textContent!;
}

function choose(fixture: ComponentFixture<SystemOneConfigFormComponent>, itemName: string): void {
    openPicker(fixture);
    Array.from(document.querySelectorAll<HTMLButtonElement>('.cdk-overlay-container button'))
        .find((button) => button.textContent!.trim() === itemName)!
        .click();
    fixture.detectChanges();
}

describe('SystemOneConfigFormComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('starts with nothing picked and no API key field', () => {
        const { fixture } = render();

        expect(pickerTrigger(fixture).textContent).toContain('Select provider');
        expect(selectFor(fixture, 'api_key_secret_id')).toBeNull();
    });

    it('offers TypeSafe, OpenAI and existing LLM configs, in that order, each with its models or LLM configs', () => {
        const { fixture } = render();

        const text = openPicker(fixture);

        expect(text.indexOf('TYPESAFE')).toBeLessThan(text.indexOf('jev-1.14.0'));
        expect(text.indexOf('jev-1.13.0')).toBeLessThan(text.indexOf('OPENAI'));
        expect(text.indexOf('OPENAI')).toBeLessThan(text.indexOf('gpt-6-luna'));
        expect(text.indexOf('gpt-6-luna')).toBeLessThan(text.indexOf('EXISTING LLM CONFIGS'));
        expect(text.indexOf('EXISTING LLM CONFIGS')).toBeLessThan(text.indexOf('gpt-judge'));
    });

    it('shows the API key select, and no provider note, after picking a Jev version', () => {
        const { fixture } = render();

        choose(fixture, 'jev-1.13.0');

        expect(pickerTrigger(fixture).textContent).toContain('TypeSafe:');
        expect(pickerTrigger(fixture).textContent).toContain('jev-1.13.0');
        expect(selectFor(fixture, 'api_key_secret_id')).not.toBeNull();
        expect(host(fixture).textContent).not.toContain(LLM_HINT);
    });

    it('shows the API key select, and no provider note, after picking gpt-6-luna', () => {
        const { fixture } = render();

        choose(fixture, 'gpt-6-luna');

        expect(selectFor(fixture, 'api_key_secret_id')).not.toBeNull();
        expect(host(fixture).textContent).not.toContain('probabilities');
    });

    it('hides the API key select and shows the LLM note after picking an LLM config', () => {
        const { fixture } = render();

        choose(fixture, 'gpt-judge');

        expect(pickerTrigger(fixture).textContent).toContain('Existing LLM configs:');
        expect(selectFor(fixture, 'api_key_secret_id')).toBeNull();
        expect(host(fixture).textContent).toContain(LLM_HINT);
    });

    it('tells the user to add an LLM config first when there are none to pick', () => {
        const { fixture } = render(null, []);

        expect(openPicker(fixture)).toContain('No LLM configs yet.');
    });

    it('does not show that hint while LLM configs exist', () => {
        const { fixture } = render();

        expect(openPicker(fixture)).not.toContain('No LLM configs yet.');
    });

    it('creates a TypeSafe config with the picked Jev version and the chosen secret', () => {
        const { fixture, http, saved } = render();
        type(fixture, 'Configuration Name', 'Jev prod');
        choose(fixture, 'jev-1.13.0');
        pick(fixture, 'api_key_secret_id', 'Jev key');

        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'POST', url: '/api/system-one-configs/' });
        request.flush({ ...TYPESAFE_CONFIG, ...request.request.body });

        expect(request.request.body).toEqual({
            custom_name: 'Jev prod',
            provider: 'typesafe',
            model_name: 'jev-1.13.0',
            api_key_secret_id: 5,
            llm_config: null,
        });
        expect(saved).toHaveBeenCalledOnce();
    });

    it('creates an OpenAI config with gpt-6-luna and the chosen secret', () => {
        const { fixture, http, saved } = render();
        choose(fixture, 'gpt-6-luna');
        type(fixture, 'Configuration Name', 'OpenAI prod');
        pick(fixture, 'api_key_secret_id', 'Jev key');

        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'POST', url: '/api/system-one-configs/' });
        request.flush({ ...OPENAI_CONFIG, ...request.request.body });

        expect(request.request.body).toEqual({
            custom_name: 'OpenAI prod',
            provider: 'openai',
            model_name: 'gpt-6-luna',
            api_key_secret_id: 5,
            llm_config: null,
        });
        expect(saved).toHaveBeenCalledOnce();
    });

    it('keeps the chosen secret when switching from TypeSafe to OpenAI', () => {
        const { fixture, http } = render();
        type(fixture, 'Configuration Name', 'OpenAI prod');
        choose(fixture, 'jev-1.14.0');
        pick(fixture, 'api_key_secret_id', 'Jev key');
        choose(fixture, 'gpt-6-luna');

        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'POST', url: '/api/system-one-configs/' });

        expect(request.request.body).toEqual({
            custom_name: 'OpenAI prod',
            provider: 'openai',
            model_name: 'gpt-6-luna',
            api_key_secret_id: 5,
            llm_config: null,
        });
    });

    it('creates an LLM config without a model or secret, even after a secret was chosen for TypeSafe', () => {
        const { fixture, http } = render();
        choose(fixture, 'jev-1.14.0');
        pick(fixture, 'api_key_secret_id', 'Jev key');
        choose(fixture, 'gpt-judge');
        type(fixture, 'Configuration Name', 'Judge');

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

    it('sends nothing and shows the required error under Provider while nothing is picked', () => {
        const { fixture, http, saved } = render();
        type(fixture, 'Configuration Name', 'Jev prod');

        fixture.componentInstance.submit();
        fixture.detectChanges();

        http.expectNone(() => true);
        expect(saved).not.toHaveBeenCalled();
        expect(pickerField(fixture).textContent).toContain('This field is required.');
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

    it.each([
        { config: TYPESAFE_CONFIG, shown: 'TYPESAFE', hidden: ['OPENAI', 'gpt-judge'] },
        { config: OPENAI_CONFIG, shown: 'OPENAI', hidden: ['TYPESAFE', 'gpt-judge'] },
        { config: LLM_EDIT_CONFIG, shown: 'gpt-judge', hidden: ['TYPESAFE', 'OPENAI'] },
    ])('offers only the $config.provider group when editing a $config.provider config', ({ config, shown, hidden }) => {
        const { fixture } = render(config, [LLM_CONFIG, OTHER_LLM_CONFIG]);

        const text = openPicker(fixture);

        expect(text).toContain(shown);
        hidden.forEach((name) => expect(text).not.toContain(name));
    });

    it('lets an edited TypeSafe config change its Jev version', () => {
        const { fixture, http } = render(TYPESAFE_CONFIG);

        expect(pickerTrigger(fixture).textContent).toContain('jev-1.13.0');
        choose(fixture, 'jev-1.14.0');
        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'PATCH', url: '/api/system-one-configs/11/' });

        expect(request.request.body.model_name).toBe('jev-1.14.0');
    });

    it('lets an edited LLM config switch to another LLM config', () => {
        const { fixture, http } = render(LLM_EDIT_CONFIG, [LLM_CONFIG, OTHER_LLM_CONFIG]);

        choose(fixture, 'claude-judge');
        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'PATCH', url: '/api/system-one-configs/13/' });

        expect(request.request.body).toEqual({
            custom_name: 'Judge',
            provider: 'llm',
            model_name: null,
            api_key_secret_id: null,
            llm_config: 8,
        });
    });

    it('updates an edited OpenAI config with its model', () => {
        const { fixture, http } = render(OPENAI_CONFIG);

        expect(pickerTrigger(fixture).textContent).toContain('OpenAI:');
        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'PATCH', url: '/api/system-one-configs/12/' });

        expect(request.request.body).toEqual({
            custom_name: 'OpenAI prod',
            provider: 'openai',
            model_name: 'gpt-6-luna',
            api_key_secret_id: 5,
            llm_config: null,
        });
    });

    it.each([
        { config: { ...OPENAI_CONFIG, model_name: null }, expected: 'gpt-6-luna' },
        { config: { ...TYPESAFE_CONFIG, model_name: null }, expected: 'jev-1.14.0' },
    ])("submits the provider's first model when an edited $config.provider config has none", ({ config, expected }) => {
        const { fixture, http } = render(config);

        expect(pickerTrigger(fixture).textContent).toContain(expected);
        fixture.componentInstance.submit();
        const request = http.expectOne({ method: 'PATCH', url: `/api/system-one-configs/${config.id}/` });

        expect(request.request.body.model_name).toBe(expected);
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
