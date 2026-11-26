import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NO_ERRORS_SCHEMA, Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { JsonEditorComponent } from '@shared/components';
import { ActionCode, NodeType, ResourceCode } from '@shared/models';
import { MarkdownComponent } from 'ngx-markdown';

import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { BaseSidePanel } from '../../core/models/node-panel.abstract';
import { buildBulkSavePayload, getNodeDiff } from '../../utils/save';
import { FLOW_ACTIONS_WITHOUT_USE, grantPermissions } from '../../utils/testing/permissions.fixture';
import { AgentNodePanelComponent } from './agent-node-panel/agent-node-panel.component';
import { agentNodeWithTasks, liveNodeOfType } from './node-panel-diff.testing';
import { TaskNodePanelComponent } from './task-node-panel/task-node-panel.component';

// A role may change flows and read agents but not read surfaces. The Agent and Task panels then hide the Surface
// field, as the Agents page hides its Surfaces section, and saving the node still sends the surfaces it holds.

interface PanelCase {
    panel: string;
    component: Type<BaseSidePanel<NodeModel>>;
    /** A node with one surface and a local surface. */
    node: () => NodeModel;
    payloadKey: string;
}

const PANELS: PanelCase[] = [
    {
        panel: 'Agent',
        component: AgentNodePanelComponent as Type<BaseSidePanel<NodeModel>>,
        node: () => agentNodeWithTasks(),
        payloadKey: 'agent_node_list',
    },
    {
        panel: 'Task',
        component: TaskNodePanelComponent as Type<BaseSidePanel<NodeModel>>,
        node: () => liveNodeOfType(NodeType.TASK),
        payloadKey: 'task_node_list',
    },
];

const LAYOUTS = PANELS.flatMap((panelCase) =>
    [false, true].map((isExpanded) => ({ ...panelCase, isExpanded, layout: isExpanded ? 'widened' : 'narrow' }))
);

const WITHOUT_SURFACES_READ = {
    [ResourceCode.Flows]: FLOW_ACTIONS_WITHOUT_USE,
    [ResourceCode.Agents]: [ActionCode.Read],
};
const WITH_SURFACES_READ = { ...WITHOUT_SURFACES_READ, [ResourceCode.Surfaces]: [ActionCode.Read] };

/** The live editor (not a version preview) for a user with exactly `permissions` in the active org. */
function openPanel(
    { component, node }: PanelCase,
    permissions: Partial<Record<ResourceCode, ActionCode[]>>,
    isExpanded = false
): ComponentFixture<BaseSidePanel<NodeModel>> {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    // Monaco and the app's Markdown setup are not available here; their elements stay bare.
    TestBed.overrideComponent(component, {
        remove: { imports: [JsonEditorComponent, MarkdownComponent] },
        add: { schemas: [NO_ERRORS_SCHEMA] },
    });
    grantPermissions(permissions);
    const fixture = TestBed.createComponent(component);
    fixture.componentRef.setInput('node', node());
    fixture.componentRef.setInput('isExpanded', isExpanded);
    fixture.detectChanges();
    return fixture;
}

function surfaceField(root: HTMLElement): { label: boolean; pickerAndSummary: boolean } {
    return {
        label: root.textContent?.includes('Surface (Group of Permissions)') ?? false,
        pickerAndSummary: root.querySelector('.surface-row') !== null,
    };
}

function rename(fixture: ComponentFixture<unknown>, name: string): void {
    const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
        'app-custom-input[formcontrolname="node_name"] input'
    )!;
    input.value = name;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

describe('Agent and Task panels: the Surface field and the surfaces read permission', () => {
    // jsdom has no ResizeObserver; the panels' tooltips shown only for cut-short text need one.
    beforeEach(() =>
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        )
    );

    it.each(LAYOUTS)('$panel ($layout): hidden without surfaces read', (panelCase) => {
        const fixture = openPanel(panelCase, WITHOUT_SURFACES_READ, panelCase.isExpanded);

        expect(surfaceField(fixture.nativeElement)).toEqual({ label: false, pickerAndSummary: false });
    });

    it.each(LAYOUTS)('$panel ($layout): shown with surfaces read', (panelCase) => {
        const fixture = openPanel(panelCase, WITH_SURFACES_READ, panelCase.isExpanded);

        expect(surfaceField(fixture.nativeElement)).toEqual({ label: true, pickerAndSummary: true });
    });

    it.each(PANELS)("$panel: saving without surfaces read sends the node's surfaces unchanged", (panelCase) => {
        const stored = panelCase.node();
        const fixture = openPanel(panelCase, WITHOUT_SURFACES_READ);

        rename(fixture, 'Renamed');
        const saved = fixture.componentInstance.onSave()!;

        const previous = { nodes: [stored], connections: [] } as unknown as FlowModel;
        const current = { nodes: [saved], connections: [] } as unknown as FlowModel;
        const payload = buildBulkSavePayload(
            1,
            getNodeDiff(previous, current),
            { toCreate: [], toDelete: [], toUpdate: [] },
            current,
            new Map(),
            1
        );
        expect(payload[panelCase.payloadKey]).toEqual([
            expect.objectContaining({
                node_name: 'Renamed',
                surface_list: [51],
                inline_surface: expect.objectContaining({ instructions: 'Be brief' }),
            }),
        ]);
    });
});
