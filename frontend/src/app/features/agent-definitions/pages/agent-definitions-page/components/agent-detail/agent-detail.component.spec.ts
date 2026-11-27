import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef, input, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { AppSvgIconComponent, HelpTooltipComponent, LlmModelSelectorComponent } from '@shared/components';
import { EnterBlurDirective, HasPermissionDirective } from '@shared/directives';
import { FullLLMConfig, FullLLMConfigService, FullRealtimeConfigService } from '@shared/services';
import { Observable, of, Subject, throwError } from 'rxjs';

import { tourAnchorSelector } from '../../../../../../core/guided-tour';
import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../services/notifications';
import { CREATE_AGENT_TOUR_ANCHORS } from '../../../../../create-agent-tour/create-agent-tour-anchors';
import { AgentDefinition } from '../../../../models/agent-definition.model';
import { RealtimeAgentDefinition } from '../../../../models/realtime-agent-definition.model';
import { RealtimeAgentDefinitionsApiService } from '../../../../services/realtime-agent-definitions-api.service';
import {
    AgentAdditionalSettingsData,
    AgentAdditionalSettingsResult,
} from './agent-additional-settings-dialog/agent-additional-settings-dialog.component';
import { AgentDetailComponent, AgentSavePayload } from './agent-detail.component';

function llmConfig(id: number, modelName: string): FullLLMConfig {
    return { id, custom_name: '', modelDetails: { name: modelName }, providerDetails: null } as FullLLMConfig;
}

const CONFIGS = [llmConfig(1, 'gpt-primary'), llmConfig(2, 'claude-backup'), llmConfig(3, 'gemini-extra')];

const AGENT: AgentDefinition = {
    id: 3,
    org: 1,
    name: 'CV Processor',
    group: null,
    description: '',
    instructions: '',
    instruction_list: [],
    llm_config: 1,
    fallback_llm_config: 2,
    fcm_llm_config: null,
    agent_definition_realtime_config_id: null,
    has_realtime_definition: false,
    default_surfaces: [],
    metadata: {},
    max_iter: 20,
    max_rpm: 10,
    max_execution_time: 60,
    prompt_caching_enabled: true,
    max_retry_limit: 2,
    default_temperature: 0.7,
    max_tool_calls: 15,
    tool_timeout: 300,
    max_consecutive_failures: 3,
    schema_max_retries: 2,
    created_at: null,
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

function render(
    agent: AgentDefinition | null,
    isCreating = false
): {
    fixture: ComponentFixture<AgentDetailComponent>;
    saved: AgentSavePayload[];
    overlay: HTMLElement;
} {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            {
                provide: FullLLMConfigService,
                useValue: { fullLLMConfigs: signal(CONFIGS), getFullLLMConfigs: () => of(CONFIGS) },
            },
            { provide: FullRealtimeConfigService, useValue: {} },
            { provide: PermissionsService, useValue: { active: signal(null), can: () => true, canAny: () => true } },
            { provide: ToastService, useValue: {} },
            { provide: RealtimeAgentDefinitionsApiService, useValue: {} },
        ],
    });
    TestBed.overrideComponent(AgentDetailComponent, {
        set: {
            imports: [
                ReactiveFormsModule,
                EnterBlurDirective,
                AppSvgIconComponent,
                LlmModelSelectorComponent,
                HelpTooltipComponent,
                MatTooltipModule,
                HasPermissionDirective,
            ],
            schemas: [CUSTOM_ELEMENTS_SCHEMA],
        },
    });
    const fixture = TestBed.createComponent(AgentDetailComponent);
    fixture.componentRef.setInput('agent', agent);
    fixture.componentRef.setInput('isCreating', isCreating);
    fixture.detectChanges();
    const saved: AgentSavePayload[] = [];
    fixture.componentInstance.save.subscribe((payload) => saved.push(payload));
    return { fixture, saved, overlay: TestBed.inject(OverlayContainer).getContainerElement() };
}

const PRIMARY = 0;
const FALLBACK = 1;

function selectorTrigger(fixture: ComponentFixture<AgentDetailComponent>, index: number): HTMLElement {
    return fixture.nativeElement.querySelectorAll('app-llm-model-selector .selected-model')[index];
}

function pickOption(
    fixture: ComponentFixture<AgentDetailComponent>,
    overlay: HTMLElement,
    index: number,
    modelName: string
): void {
    selectorTrigger(fixture, index).click();
    fixture.detectChanges();
    const option = Array.from(overlay.querySelectorAll<HTMLElement>('.model-item')).find((item) =>
        item.textContent?.includes(modelName)
    );
    option!.click();
    fixture.detectChanges();
}

function clearSelection(fixture: ComponentFixture<AgentDetailComponent>, overlay: HTMLElement, index: number): void {
    selectorTrigger(fixture, index).click();
    fixture.detectChanges();
    overlay.querySelector<HTMLElement>('.deselect-option')!.click();
    fixture.detectChanges();
}

// jsdom has no ResizeObserver; the selector's overflow tooltips only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('AgentDetailComponent fallback LLM', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('shows the saved fallback in its own selector', () => {
        const { fixture } = render(AGENT);

        expect(selectorTrigger(fixture, FALLBACK).textContent).toContain('claude-backup');
    });

    it('saves a newly picked fallback together with the primary', () => {
        const { fixture, saved, overlay } = render({ ...AGENT, fallback_llm_config: null });

        pickOption(fixture, overlay, FALLBACK, 'gemini-extra');

        expect(saved).toHaveLength(1);
        expect(saved[0]).toMatchObject({ llm_config: 1, fallback_llm_config: 3 });
    });

    it('does not offer the primary as a fallback', () => {
        const { fixture, overlay } = render({ ...AGENT, fallback_llm_config: null });

        selectorTrigger(fixture, FALLBACK).click();
        fixture.detectChanges();

        const names = Array.from(overlay.querySelectorAll('.models-list .model-name')).map((el) =>
            el.textContent?.trim()
        );
        expect(names).toEqual(['claude-backup', 'gemini-extra']);
    });

    it('saves a cleared fallback', () => {
        const { fixture, saved, overlay } = render(AGENT);

        clearSelection(fixture, overlay, FALLBACK);

        expect(saved).toHaveLength(1);
        expect(saved[0]).toMatchObject({ llm_config: 1, fallback_llm_config: null });
    });

    it('clears the fallback in the same save when the primary is changed to it', () => {
        const { fixture, saved, overlay } = render(AGENT);

        pickOption(fixture, overlay, PRIMARY, 'claude-backup');

        expect(saved).toHaveLength(1);
        expect(saved[0]).toMatchObject({ llm_config: 2, fallback_llm_config: null });
        expect(selectorTrigger(fixture, FALLBACK).textContent).not.toContain('claude-backup');
    });

    it('clears the fallback in the same save when the primary is cleared', () => {
        const { fixture, saved, overlay } = render(AGENT);

        clearSelection(fixture, overlay, PRIMARY);

        expect(saved).toHaveLength(1);
        expect(saved[0]).toMatchObject({ llm_config: null, fallback_llm_config: null });
    });

    it('keeps the fallback when the primary is changed to a different config', () => {
        const { fixture, saved, overlay } = render(AGENT);

        pickOption(fixture, overlay, PRIMARY, 'gemini-extra');

        expect(saved).toHaveLength(1);
        expect(saved[0]).toMatchObject({ llm_config: 3, fallback_llm_config: 2 });
    });

    it('locks the fallback selector while there is no primary', () => {
        const { fixture } = render({ ...AGENT, llm_config: null, fallback_llm_config: null });

        selectorTrigger(fixture, FALLBACK).click();
        fixture.detectChanges();

        expect(selectorTrigger(fixture, FALLBACK).classList).toContain('readonly');
        expect(TestBed.inject(OverlayContainer).getContainerElement().querySelector('.dropdown-menu')).toBeNull();
    });
});

describe('AgentDetailComponent unsaved edits', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    /** What the editor last told the page: does it hold edits that aren't saved? */
    function lastDirty(fixture: ComponentFixture<AgentDetailComponent>): () => boolean | undefined {
        const emitted: boolean[] = [];
        fixture.componentInstance.dirtyChange.subscribe((dirty) => emitted.push(dirty));
        return () => emitted.at(-1);
    }

    it('counts a model picked on a nameless draft as unsaved, since the draft is not created', () => {
        const { fixture, saved, overlay } = render(null, true);
        const dirty = lastDirty(fixture);

        pickOption(fixture, overlay, PRIMARY, 'gpt-primary');

        expect(saved).toEqual([]);
        expect(dirty()).toBe(true);
    });

    function typeName(fixture: ComponentFixture<AgentDetailComponent>, name: string): void {
        const input = fixture.nativeElement.querySelector('input[aria-label="Agent Name"]') as HTMLInputElement;
        input.value = name;
        input.dispatchEvent(new Event('input'));
        input.dispatchEvent(new Event('blur'));
        fixture.detectChanges();
    }

    it('keeps a draft unsaved when creating it fails', () => {
        const { fixture, saved } = render(null, true);
        typeName(fixture, 'CV Processor');
        expect(saved).toHaveLength(1);
        // The page took the save as the end of the edits; the failure has to say otherwise.
        const dirty = lastDirty(fixture);

        fixture.componentRef.setInput('saveErrorTick', 1);
        fixture.detectChanges();

        expect(dirty()).toBe(true);
    });

    it('drops the draft name error when another agent is opened', () => {
        const { fixture } = render(null, true);
        fixture.componentInstance.requireName();
        fixture.detectChanges();

        fixture.componentRef.setInput('isCreating', false);
        fixture.componentRef.setInput('agent', { ...AGENT, id: 8 });
        fixture.detectChanges();
        const input = fixture.nativeElement.querySelector('input[aria-label="Agent Name"]') as HTMLInputElement;
        input.value = '';
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();

        expect(fixture.nativeElement.querySelector('.field__error')).toBeNull();
    });

    it('saves a model picked while the draft was being created, and is unsaved until then', () => {
        const { fixture, saved, overlay } = render(null, true);
        typeName(fixture, 'CV Processor');
        pickOption(fixture, overlay, PRIMARY, 'gpt-primary');
        const events: string[] = [];
        fixture.componentInstance.dirtyChange.subscribe((dirty) => events.push(`dirty:${dirty}`));
        fixture.componentInstance.save.subscribe(() => events.push('save'));

        fixture.componentRef.setInput('isCreating', false);
        fixture.componentRef.setInput('createdFromDraft', true);
        fixture.componentRef.setInput('agent', {
            ...AGENT,
            name: 'CV Processor',
            llm_config: null,
            fallback_llm_config: null,
        });
        fixture.detectChanges();

        // The page hears "unsaved" right before the save that clears it.
        expect(events.slice(-2)).toEqual(['dirty:true', 'save']);
        expect(saved.at(-1)).toMatchObject({ id: AGENT.id, llm_config: 1 });
    });

    it('shows what the server created for fields not edited while the draft was being created', () => {
        const { fixture, saved } = render(null, true);
        // Adding an instruction to a nameless draft creates it; the store names it.
        fixture.debugElement
            .query(By.css('app-agent-instructions-list'))
            .triggerEventHandler('instructionListChange', [{ name: 'Instruction 1', content: '' }]);
        expect(saved).toHaveLength(1);

        fixture.componentRef.setInput('isCreating', false);
        fixture.componentRef.setInput('createdFromDraft', true);
        fixture.componentRef.setInput('agent', { ...AGENT, name: 'Untitled Agent' });
        fixture.detectChanges();

        const name = fixture.nativeElement.querySelector('input[aria-label="Agent Name"]') as HTMLInputElement;
        expect(name.value).toBe('Untitled Agent');
        expect(selectorTrigger(fixture, PRIMARY).textContent).toContain('gpt-primary');
        expect(saved).toHaveLength(1);
    });

    it("does not carry a discarded draft's model to the agent opened next", () => {
        const { fixture, saved, overlay } = render(null, true);
        pickOption(fixture, overlay, PRIMARY, 'gpt-primary');

        fixture.componentRef.setInput('isCreating', false);
        fixture.componentRef.setInput('agent', { ...AGENT, llm_config: null, fallback_llm_config: null });
        fixture.detectChanges();

        expect(saved).toEqual([]);
        expect(selectorTrigger(fixture, PRIMARY).textContent).not.toContain('gpt-primary');
    });

    it('counts the saved model picked again as no change', () => {
        const { fixture, saved, overlay } = render(AGENT);
        const dirty = lastDirty(fixture);

        pickOption(fixture, overlay, PRIMARY, 'gpt-primary');

        expect(saved).toEqual([]);
        expect(dirty()).toBe(false);
    });
});

/** Stands in for the LLM model selector, which loads every LLM configuration of the organization. */
@Component({
    selector: 'app-llm-model-selector',
    template: '',
    providers: [
        { provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => LlmModelSelectorStubComponent), multi: true },
    ],
})
class LlmModelSelectorStubComponent implements ControlValueAccessor {
    readonly excludedConfigId = input<number | null>(null);
    readonly readonly = input(false);

    private onChange: (configId: number | null) => void = () => {};

    writeValue(): void {}

    registerOnChange(onChange: (configId: number | null) => void): void {
        this.onChange = onChange;
    }

    registerOnTouched(): void {}

    /** What picking a config in the dropdown hands to the form. */
    pick(configId: number | null): void {
        this.onChange(configId);
    }
}

describe('AgentDetailComponent Create Agent tour anchors', () => {
    function render(inputs: { agent: AgentDefinition | null; isCreating: boolean }): HTMLElement {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
            ],
        });
        // The form is under test; the instructions list and the Surfaces panel stay unrendered custom elements.
        TestBed.overrideComponent(AgentDetailComponent, {
            set: {
                imports: [
                    ReactiveFormsModule,
                    EnterBlurDirective,
                    HasPermissionDirective,
                    LlmModelSelectorStubComponent,
                ],
                schemas: [CUSTOM_ELEMENTS_SCHEMA],
            },
        });
        const fixture = TestBed.createComponent(AgentDetailComponent);
        fixture.componentRef.setInput('agent', inputs.agent);
        fixture.componentRef.setInput('isCreating', inputs.isCreating);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    function labelOf(host: HTMLElement, anchor: string): string | undefined {
        return host.querySelector(tourAnchorSelector(anchor))?.querySelector('label')?.textContent?.trim();
    }

    it('marks the name field of a draft', () => {
        const host = render({ agent: null, isCreating: true });

        expect(labelOf(host, CREATE_AGENT_TOUR_ANCHORS.agentName)).toContain('Agent Name');
    });

    it('puts the cursor in the name field when creating', async () => {
        const host = render({ agent: null, isCreating: true });
        await new Promise((resolve) => setTimeout(resolve));

        expect(document.activeElement).toBe(host.querySelector('input[aria-label="Agent Name"]'));
    });

    it("leaves a saved agent's name field unmarked: the tour must not take it for the draft's", () => {
        const host = render({ agent: AGENT, isCreating: false });

        expect(host.querySelector(tourAnchorSelector(CREATE_AGENT_TOUR_ANCHORS.agentName))).toBeNull();
    });

    it("marks a saved agent's model, instructions and Surfaces", () => {
        const host = render({ agent: AGENT, isCreating: false });

        expect(labelOf(host, CREATE_AGENT_TOUR_ANCHORS.llmConfig)).toContain('LLM Configuration');
        expect(labelOf(host, CREATE_AGENT_TOUR_ANCHORS.instructions)).toContain('Instructions');
        expect(host.querySelector(tourAnchorSelector(CREATE_AGENT_TOUR_ANCHORS.surfaces))?.textContent).toContain(
            'Surfaces'
        );
    });
});

describe('AgentDetailComponent prompt caching settings', () => {
    /** Configs 1 and 2 run Claude, config 3 does not. */
    const PROMPT_CACHE_CONFIGS = [
        { id: 1, needs_prompt_cache_markers: true },
        { id: 2, needs_prompt_cache_markers: true },
        { id: 3, needs_prompt_cache_markers: false },
        { id: 4, needs_prompt_cache_markers: false },
    ] as FullLLMConfig[];

    const NO_VOICE: RealtimeAgentDefinition = {
        agent_definition: AGENT.id,
        openai_config: null,
        elevenlabs_config: null,
        gemini_config: null,
        voice: '',
        wake_word: null,
        stop_prompt: null,
        language: null,
        voice_recognition_prompt: null,
    };

    /** What the user saved in the dialog: everything as stored, prompt caching switched off. */
    const DIALOG_RESULT: AgentAdditionalSettingsResult = {
        fcm_llm_config: null,
        openai_config: null,
        elevenlabs_config: null,
        gemini_config: null,
        voice: '',
        max_iter: AGENT.max_iter,
        max_rpm: AGENT.max_rpm,
        max_execution_time: AGENT.max_execution_time,
        max_retry_limit: AGENT.max_retry_limit,
        prompt_caching_enabled: false,
        max_tool_calls: AGENT.max_tool_calls,
        tool_timeout: AGENT.tool_timeout,
        max_consecutive_failures: AGENT.max_consecutive_failures,
        schema_max_retries: AGENT.schema_max_retries,
    };

    /** Shows the agent; the configs load only when Additional Settings asks for them, as with Basics collapsed. */
    function renderAgent(
        agent: AgentDefinition,
        configs: Observable<FullLLMConfig[]> = of(PROMPT_CACHE_CONFIGS),
        realtimeApi: Partial<RealtimeAgentDefinitionsApiService> = { getByAgentId: () => of(NO_VOICE) }
    ): {
        fixture: ComponentFixture<AgentDetailComponent>;
        opened: AgentAdditionalSettingsData[];
        saved: AgentSavePayload[];
    } {
        const opened: AgentAdditionalSettingsData[] = [];
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: FullLLMConfigService,
                    useValue: { fullLLMConfigs: signal([]), getFullLLMConfigs: () => configs },
                },
                { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
                { provide: ToastService, useValue: {} },
                { provide: RealtimeAgentDefinitionsApiService, useValue: realtimeApi },
                {
                    provide: Dialog,
                    useValue: {
                        open: (_component: unknown, config: { data: AgentAdditionalSettingsData }) => {
                            opened.push(config.data);
                            return { closed: of(DIALOG_RESULT) };
                        },
                    },
                },
            ],
        });
        TestBed.overrideComponent(AgentDetailComponent, {
            set: {
                imports: [
                    ReactiveFormsModule,
                    EnterBlurDirective,
                    HasPermissionDirective,
                    LlmModelSelectorStubComponent,
                ],
                schemas: [CUSTOM_ELEMENTS_SCHEMA],
            },
        });
        const fixture = TestBed.createComponent(AgentDetailComponent);
        fixture.componentRef.setInput('agent', agent);
        fixture.detectChanges();
        const saved: AgentSavePayload[] = [];
        fixture.componentInstance.save.subscribe((payload) => saved.push(payload));
        return { fixture, opened, saved };
    }

    function clickAdditionalSettings(fixture: ComponentFixture<AgentDetailComponent>): void {
        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('[aria-label="Additional Settings"]')!
            .click();
    }

    function openSettings(
        agent: AgentDefinition,
        configs?: Observable<FullLLMConfig[]>
    ): { opened: AgentAdditionalSettingsData[]; saved: AgentSavePayload[] } {
        const { fixture, opened, saved } = renderAgent(agent, configs);
        clickAdditionalSettings(fixture);
        return { opened, saved };
    }

    /** Picks a config in the primary selector without saving the agent. */
    function pickPrimary(fixture: ComponentFixture<AgentDetailComponent>, configId: number): void {
        fixture.debugElement
            .queryAll(By.directive(LlmModelSelectorStubComponent))
            [PRIMARY].componentInstance.pick(configId);
        fixture.detectChanges();
    }

    it.each([
        { case: 'a Claude primary', llm_config: 1, fallback_llm_config: 3, available: true },
        { case: 'a Claude fallback only', llm_config: 3, fallback_llm_config: 2, available: true },
        { case: 'no Claude config', llm_config: 3, fallback_llm_config: 4, available: false },
        { case: 'no config picked', llm_config: null, fallback_llm_config: null, available: false },
    ])('offers prompt caching for $case: $available', ({ llm_config, fallback_llm_config, available }) => {
        const { opened } = openSettings({ ...AGENT, llm_config, fallback_llm_config });

        expect(opened).toHaveLength(1);
        expect(opened[0].promptCachingAvailable).toBe(available);
    });

    it('hands the stored setting to the dialog and saves what the dialog returns, under its new name only', () => {
        const { opened, saved } = openSettings({ ...AGENT, prompt_caching_enabled: true });

        expect(opened[0].prompt_caching_enabled).toBe(true);
        expect(saved).toHaveLength(1);
        expect(saved[0].prompt_caching_enabled).toBe(false);
        expect(saved[0]).not.toHaveProperty('cache');
    });

    it('saves the agent without touching voice settings when the agent has none and no provider is picked', () => {
        const partialUpdate = vi.fn();
        const create = vi.fn();
        const { fixture, saved } = renderAgent(AGENT, of(PROMPT_CACHE_CONFIGS), {
            getByAgentId: () => of(null),
            partialUpdate,
            create,
        });

        clickAdditionalSettings(fixture);

        expect(partialUpdate).not.toHaveBeenCalled();
        expect(create).not.toHaveBeenCalled();
        expect(saved).toHaveLength(1);
    });

    it('still opens the settings, without prompt caching, when the configs fail to load', () => {
        const { opened } = openSettings(
            AGENT,
            throwError(() => new Error('configs unavailable'))
        );

        expect(opened).toHaveLength(1);
        expect(opened[0].promptCachingAvailable).toBe(false);
    });

    it.each([
        { case: 'a Claude primary picked over a saved other one', saved: 3, picked: 1, available: true },
        { case: 'another primary picked over a saved Claude one', saved: 1, picked: 4, available: false },
    ])('offers prompt caching by the unsaved form for $case: $available', ({ saved, picked, available }) => {
        const { fixture, opened } = renderAgent({ ...AGENT, llm_config: saved, fallback_llm_config: 3 });

        pickPrimary(fixture, picked);
        clickAdditionalSettings(fixture);

        expect(opened).toHaveLength(1);
        expect(opened[0].promptCachingAvailable).toBe(available);
    });

    it('waits for the configs before opening the settings', () => {
        const configs = new Subject<FullLLMConfig[]>();
        const { opened } = openSettings({ ...AGENT, llm_config: 1, fallback_llm_config: 3 }, configs);

        expect(opened).toEqual([]);

        configs.next(PROMPT_CACHE_CONFIGS);
        configs.complete();

        expect(opened).toHaveLength(1);
        expect(opened[0].promptCachingAvailable).toBe(true);
    });
});
