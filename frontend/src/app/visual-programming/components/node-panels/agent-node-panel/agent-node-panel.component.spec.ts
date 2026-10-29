import { Dialog } from '@angular/cdk/dialog';
import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
import { NodeType } from '@shared/models';
import { of, Subject } from 'rxjs';

import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
import { SurfacesApiService } from '../../../../features/agent-definitions/services/surfaces-api.service';
import { ToastService } from '../../../../services/notifications';
import { IfFlowEditableDirective } from '../../../core/directives/if-flow-editable.directive';
import { AgentNodeTaskUi } from '../../../core/models/agent-node.model';
import { AgentNodeModel } from '../../../core/models/node.model';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { NodeSurfaceCombineApiService } from '../../../services/node-surface-combine-api.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { InputsYouCanUseComponent } from '../shared/inputs-you-can-use/inputs-you-can-use.component';
import { LocalSurfaceDialogService } from '../shared/local-surface-dialog/local-surface-dialog.service';
import { AgentNodePanelComponent } from './agent-node-panel.component';
import { AgentTasksTableComponent } from './agent-tasks-table/agent-tasks-table.component';

// Stands in for the form-bound shared controls so the real template renders without their dependencies.
@Component({
    selector: 'app-custom-input',
    template: '',
    providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => FormControlStubComponent), multi: true }],
})
class FormControlStubComponent implements ControlValueAccessor {
    writeValue(): void {}
    registerOnChange(): void {}
    registerOnTouched(): void {}
}

function task(tempId: string, instructions: string): AgentNodeTaskUi {
    return { tempId, name: tempId, instructions, output_schema: {}, contextRefs: [] };
}

function agentNode(id: string, tempIdPrefix = ''): AgentNodeModel {
    return {
        id,
        backendId: 1,
        nodeUuid: null,
        type: NodeType.AGENT,
        position: { x: 0, y: 0 },
        ports: null,
        node_name: 'Agent',
        color: '',
        icon: '',
        size: { width: 0, height: 0 },
        input_map: { topic: 'variables.topic' },
        output_variable_path: null,
        data: {
            name: 'Agent',
            agent_definition: 1,
            surface_list: [],
            inline_surface: null,
            tasks: [task(`${tempIdPrefix}first`, 'alpha'), task(`${tempIdPrefix}second`, 'beta')],
        },
    };
}

function createCollapsedPanel(): ComponentFixture<AgentNodePanelComponent> {
    TestBed.configureTestingModule({
        providers: [
            { provide: AgentDefinitionsApiService, useValue: { getAgentDefinitions: () => of([]) } },
            { provide: SurfacesApiService, useValue: { getSurfaces: () => of([]) } },
            {
                provide: SidePanelService,
                useValue: {
                    graphSaved$: new Subject<void>(),
                    triggerAutosave: vi.fn(),
                    requestExpand: vi.fn(),
                    selectedNode: signal(null),
                },
            },
            { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false), isNodeTypeReadOnly: () => false } },
            { provide: ToastService, useValue: { warning: vi.fn(), error: vi.fn(), success: vi.fn() } },
            { provide: LocalSurfaceDialogService, useValue: { open: vi.fn() } },
            { provide: NodeSurfaceCombineApiService, useValue: {} },
            { provide: Dialog, useValue: { open: vi.fn() } },
        ],
    });
    // The real table and chip list are what the user clicks; the rest of the template is stubbed out.
    TestBed.overrideComponent(AgentNodePanelComponent, {
        set: {
            imports: [
                ReactiveFormsModule,
                FormControlStubComponent,
                AgentTasksTableComponent,
                InputsYouCanUseComponent,
                IfFlowEditableDirective,
            ],
            schemas: [CUSTOM_ELEMENTS_SCHEMA],
        },
    });
    const fixture = TestBed.createComponent(AgentNodePanelComponent);
    fixture.componentRef.setInput('node', agentNode('node-1'));
    fixture.detectChanges();
    return fixture;
}

function instructionsTextareas(fixture: ComponentFixture<AgentNodePanelComponent>): HTMLTextAreaElement[] {
    return Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLTextAreaElement>('.att-cell--instructions textarea')
    );
}

function clickInputChip(fixture: ComponentFixture<AgentNodePanelComponent>, name: string): void {
    const root = fixture.nativeElement as HTMLElement;
    if (!root.querySelector('.inputs-chip-list')) {
        root.querySelector<HTMLButtonElement>('.inputs-list-toggle')!.click();
        fixture.detectChanges();
    }
    const chip = Array.from(root.querySelectorAll<HTMLElement>('.inputs-chip')).find(
        (element) => element.textContent?.trim() === name
    );
    chip!.click();
    fixture.detectChanges();
}

function instructionsOf(fixture: ComponentFixture<AgentNodePanelComponent>): string[] {
    return fixture.componentInstance.tasks().map((row) => row.instructions);
}

describe('AgentNodePanelComponent inserting an input into instructions (collapsed layout)', () => {
    it('inserts into the task whose instructions cell was focused, at the caret', () => {
        const fixture = createCollapsedPanel();
        const secondTextarea = instructionsTextareas(fixture)[1];
        secondTextarea.focus();
        secondTextarea.setSelectionRange(2, 2);

        clickInputChip(fixture, 'topic');

        expect(instructionsOf(fixture)).toEqual(['alpha', 'be {topic}ta']);
        expect(TestBed.inject(SidePanelService).requestExpand).not.toHaveBeenCalled();
    });

    it('falls back to the first task after the panel is reopened, until a cell is focused again', () => {
        const fixture = createCollapsedPanel();
        instructionsTextareas(fixture)[1].focus();

        // A different node with its own task ids: the rows are rebuilt, as when the panel is reopened.
        fixture.componentRef.setInput('node', agentNode('node-2', 'reopened-'));
        fixture.detectChanges();
        clickInputChip(fixture, 'topic');
        expect(instructionsOf(fixture)).toEqual(['alpha {topic}', 'beta']);

        const secondTextarea = instructionsTextareas(fixture)[1];
        secondTextarea.focus();
        secondTextarea.setSelectionRange(4, 4);
        clickInputChip(fixture, 'topic');

        expect(instructionsOf(fixture)).toEqual(['alpha {topic}', 'beta {topic}']);
    });
});
