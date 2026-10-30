import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
import { EnterBlurDirective, HasPermissionDirective } from '@shared/directives';

import { tourAnchorSelector } from '../../../../../../core/guided-tour';
import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { CREATE_AGENT_TOUR_ANCHORS } from '../../../../../create-agent-tour/create-agent-tour-anchors';
import { AgentDefinition } from '../../../../models/agent-definition.model';
import { AgentDetailComponent } from './agent-detail.component';

const AGENT: AgentDefinition = {
    id: 3,
    org: 1,
    name: 'CV Processor',
    description: '',
    instructions: '',
    instruction_list: [],
    llm_config: null,
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
    created_at: '2026-03-12T13:28:23Z',
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    last_edited_by: null,
    last_edited_at: null,
};

/** Stands in for the LLM model selector, which loads every LLM configuration of the organization. */
@Component({
    selector: 'app-llm-model-selector',
    template: '',
    providers: [
        { provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => LlmModelSelectorStubComponent), multi: true },
    ],
})
class LlmModelSelectorStubComponent implements ControlValueAccessor {
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
