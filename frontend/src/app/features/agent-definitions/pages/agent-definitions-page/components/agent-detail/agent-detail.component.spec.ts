import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef, input, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, HelpTooltipComponent, LlmModelSelectorComponent } from '@shared/components';
import { EnterBlurDirective, HasPermissionDirective } from '@shared/directives';
import { FullLLMConfig, FullLLMConfigService, FullRealtimeConfigService } from '@shared/services';
import { of } from 'rxjs';

import { tourAnchorSelector } from '../../../../../../core/guided-tour';
import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../services/notifications';
import { CREATE_AGENT_TOUR_ANCHORS } from '../../../../../create-agent-tour/create-agent-tour-anchors';
import { AgentDefinition } from '../../../../models/agent-definition.model';
import { RealtimeAgentDefinitionsApiService } from '../../../../services/realtime-agent-definitions-api.service';
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
    cache: true,
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

function render(agent: AgentDefinition): {
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

    writeValue(): void {}

    registerOnChange(): void {}

    registerOnTouched(): void {}
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
