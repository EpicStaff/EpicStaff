import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, input, Type } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { provideLoadedExecutionTimeoutLimits } from '../../../shared/services/execution-timeout-limits/execution-timeout-limits.testing';
import { NodeModel } from '../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../core/providers/flow-editor-preview.token';
import { FlowService } from '../../services/flow.service';
import { KeyValueEntryDraftsService } from '../../services/key-value-entry-drafts.service';
import { MissingReference } from '../../utils/diff';
import { buildFlowModelFromGraphDto } from '../../utils/load';
import { liveGraph } from '../../utils/testing/live-graph.fixture';
import {
    missingReference,
    provideChangesTabDiff,
    renderOnlyMissingReferenceNotes,
    shownMissingReferenceNotes,
} from '../missing-reference-note/missing-reference-note.testing';
import { NodeSecretsFieldComponent } from '../node-secrets-field/node-secrets-field.component';
import { AgentNodePanelComponent } from './agent-node-panel/agent-node-panel.component';
import { ClassificationDecisionTableNodePanelComponent } from './classification-decision-table-node-panel/classification-decision-table-node-panel.component';
import { DecisionTableNodePanelComponent } from './decision-table-node-panel/decision-table-node-panel.component';
import { KeyValueNodePanelComponent } from './key-value-node-panel/key-value-node-panel.component';
import { PythonNodePanelComponent } from './python-node-panel/python-node-panel.component';
import { SubGraphNodePanelComponent } from './subgraph-node-panel/subgraph-node-panel.component';
import { TaskNodePanelComponent } from './task-node-panel/task-node-panel.component';
import { TelegramTriggerNodePanelComponent } from './telegram-trigger-node-panel/telegram-trigger-node-panel.component';
import { WebhookTriggerNodePanelComponent } from './webhook-trigger-node-panel/webhook-trigger-node-panel.component';

// Each panel's own template is rendered on the Changes tab of a version preview, with only the notes real (the
// secrets picker too, which renders its own). A note must sit under the field its reference belongs to.

/** Left unrendered, `app-input-map` would get its `nodeName` input written to the element's read-only DOM property. */
@Component({ selector: 'app-input-map', template: '' })
class InputMapStandInComponent {
    readonly nodeName = input<unknown>();
}

/**
 * Where a note sits: `inside` the field element, right `after` it, or `beside` it in the same field container
 * (the field is then named by an element only it has).
 */
type Placement = { inside: string } | { after: string } | { beside: string };

interface ExpectedNote {
    text: string;
    placement: Placement;
}

interface PanelCase {
    panel: string;
    component: Type<unknown>;
    type: NodeType;
    references: MissingReference[];
    notes: ExpectedNote[];
    inputs?: Record<string, unknown>;
    /** What the user does first to see the field, e.g. open a tab. */
    reveal?: (panel: unknown) => void;
}

const SECRETS_PICKER: Placement = { inside: 'app-node-secrets-field' };
const TRIGGER_PICKER: Placement = { after: 'app-webhook-trigger-select' };
const AGENT_PICKER: Placement = { beside: '[searchplaceholder="Search agent..."]' };
const SURFACE_PICKER: Placement = { beside: '.surface-row' };

const AGENT_NOTES: ExpectedNote[] = [
    { text: 'This version uses agent #41; it no longer exists.', placement: AGENT_PICKER },
    { text: 'This version uses surface #5; it no longer exists.', placement: SURFACE_PICKER },
    { text: 'This version uses tool #12; it no longer exists.', placement: SURFACE_PICKER },
];
const AGENT_REFERENCES = [
    missingReference('agent_definition', 41),
    missingReference('surface_list', 5),
    missingReference('inline_surface', 12),
];

const PANEL_CASES: PanelCase[] = [
    {
        panel: 'Python',
        component: PythonNodePanelComponent,
        type: NodeType.PYTHON,
        references: [missingReference('python_code.secret_names', 'DB_PASS')],
        notes: [{ text: 'This version uses the secret DB_PASS; it no longer exists.', placement: SECRETS_PICKER }],
    },
    {
        panel: 'Webhook trigger',
        component: WebhookTriggerNodePanelComponent,
        type: NodeType.WEBHOOK_TRIGGER,
        references: [missingReference('webhook_trigger', 8), missingReference('python_code.secret_names', 'DB_PASS')],
        notes: [
            { text: 'This version uses trigger #8; it no longer exists.', placement: TRIGGER_PICKER },
            { text: 'This version uses the secret DB_PASS; it no longer exists.', placement: SECRETS_PICKER },
        ],
    },
    {
        panel: 'Classification table (routes)',
        component: ClassificationDecisionTableNodePanelComponent,
        type: NodeType.CLASSIFICATION_TABLE,
        references: [
            missingReference('condition_groups[].next_node', 3, 'condition_groups[name=high].next_node'),
            missingReference('default_next_node', 4),
        ],
        notes: [
            {
                text: 'In this version, group high routes to a node that no longer exists.',
                placement: { after: 'app-classification-decision-table-grid' },
            },
            {
                text: 'In this version, the default route leads to a node that no longer exists.',
                placement: { after: 'app-classification-decision-table-grid' },
            },
        ],
    },
    ...(['pre', 'post'] as const).map(
        (stage): PanelCase => ({
            panel: `Classification table (${stage}-computation)`,
            component: ClassificationDecisionTableNodePanelComponent,
            type: NodeType.CLASSIFICATION_TABLE,
            references: [
                missingReference('pre_computation.secret_names', 'PRE_KEY'),
                missingReference('post_computation.secret_names', 'POST_KEY'),
            ],
            notes: [
                {
                    text: `This version uses the secret ${stage.toUpperCase()}_KEY; it no longer exists.`,
                    placement: SECRETS_PICKER,
                },
            ],
            reveal: (panel) =>
                (panel as ClassificationDecisionTableNodePanelComponent).setActiveTab(`${stage}computation`),
        })
    ),
    {
        panel: 'Decision table',
        component: DecisionTableNodePanelComponent,
        type: NodeType.TABLE,
        references: [
            missingReference('condition_groups[].next_node', 3, 'condition_groups[name=yes].next_node'),
            missingReference('next_error_node', 4),
        ],
        notes: [
            {
                text: 'In this version, group yes routes to a node that no longer exists.',
                placement: { after: 'app-decision-table-grid' },
            },
            {
                text: 'In this version, the error route leads to a node that no longer exists.',
                placement: { after: 'app-decision-table-grid' },
            },
        ],
    },
    {
        panel: 'Telegram trigger',
        component: TelegramTriggerNodePanelComponent,
        type: NodeType.TELEGRAM_TRIGGER,
        references: [
            missingReference('telegram_bot_api_key_secret_id', 'BOT_TOKEN'),
            missingReference('webhook_trigger', 8),
        ],
        notes: [
            {
                text: 'This version uses the secret BOT_TOKEN; it no longer exists.',
                placement: { beside: '[formcontrolname="telegram_bot_api_key_secret_id"]' },
            },
            { text: 'This version uses trigger #8; it no longer exists.', placement: TRIGGER_PICKER },
        ],
    },
    {
        panel: 'Key-Value',
        component: KeyValueNodePanelComponent,
        type: NodeType.KEY_VALUE,
        references: [missingReference('key_value_table', 'orders')],
        notes: [
            {
                text: 'This version uses the table orders; it no longer exists.',
                placement: { after: '.table-mode-row' },
            },
        ],
    },
    {
        panel: 'Subflow',
        component: SubGraphNodePanelComponent,
        type: NodeType.SUBGRAPH,
        references: [missingReference('subgraph', 17)],
        notes: [
            {
                text: 'This version uses flow #17; it no longer exists.',
                placement: { beside: '[formcontrolname="selectedFlowId"]' },
            },
        ],
    },
    ...[false, true].flatMap((isExpanded): PanelCase[] => [
        {
            panel: `Agent (${isExpanded ? 'widened' : 'narrow'})`,
            component: AgentNodePanelComponent,
            type: NodeType.AGENT,
            references: AGENT_REFERENCES,
            notes: AGENT_NOTES,
            inputs: { isExpanded },
        },
        {
            panel: `Task (${isExpanded ? 'widened' : 'narrow'})`,
            component: TaskNodePanelComponent,
            type: NodeType.TASK,
            references: AGENT_REFERENCES,
            notes: AGENT_NOTES,
            inputs: { isExpanded },
        },
    ]),
];

function sitsAt(host: Element, placement: Placement): boolean {
    if ('inside' in placement) return host.parentElement?.closest(placement.inside) != null;
    if ('after' in placement) {
        // Right after the field, or after the version diff's field mark wrapped around it.
        const previous = host.previousElementSibling;
        if (previous?.matches('app-diff-field-mark'))
            return previous.firstElementChild?.matches(placement.after) ?? false;
        return previous?.matches(placement.after) ?? false;
    }
    return host.parentElement?.querySelector(placement.beside) != null;
}

function openOnChangesTab({ component, type, references, inputs, reveal }: PanelCase): HTMLElement {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            provideLoadedExecutionTimeoutLimits(),
            { provide: FLOW_EDITOR_PREVIEW, useValue: true },
            { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => false } },
            // The flow graph provides it to the panels.
            KeyValueEntryDraftsService,
            provideChangesTabDiff({ missingReferences: references }),
        ],
    });
    renderOnlyMissingReferenceNotes(component, [NodeSecretsFieldComponent, InputMapStandInComponent]);
    const flow = buildFlowModelFromGraphDto(liveGraph);
    TestBed.inject(FlowService).setFlow(flow);
    const node: NodeModel = flow.nodes.find((candidate) => candidate.type === type)!;

    const fixture = TestBed.createComponent(component);
    fixture.componentRef.setInput('node', node);
    for (const [name, value] of Object.entries(inputs ?? {})) fixture.componentRef.setInput(name, value);
    fixture.detectChanges();
    reveal?.(fixture.componentInstance);
    fixture.detectChanges();
    return fixture.nativeElement;
}

describe('Node panels on the Changes tab of a version preview', () => {
    it.each(PANEL_CASES)('$panel: says under each field what the version used there that is gone', (panelCase) => {
        const root = openOnChangesTab(panelCase);

        const notes = shownMissingReferenceNotes(root).map(({ text, note }) => ({
            text,
            host: note.closest('app-missing-reference-note')!,
        }));
        expect(notes.map(({ text }) => text)).toEqual(panelCase.notes.map(({ text }) => text));
        notes.forEach(({ host }, index) => expect(sitsAt(host, panelCase.notes[index].placement)).toBe(true));
    });
});
