import { Component, computed, inject, input } from '@angular/core';
import { WarningNoteComponent } from '@shared/components';

import { NODE_PANEL_DIFF } from '../../core/providers/node-panel-diff.token';
import { FieldName, MissingReference } from '../../utils/diff';

/** Every route of a decision table: one note under the routes grid covers them all. */
export const ROUTE_DIFF_FIELDS: readonly FieldName[] = [
    'condition_groups[].next_node',
    'default_next_node',
    'next_error_node',
];

const ROUTE_GROUP_PATH = /^condition_groups\[name=(.*)\]\.next_node$/;

/**
 * Says, under a field of a node panel, what the previewed version referenced there that no longer exists, so a
 * restore cannot bring it back. Changes tab of a version preview only: elsewhere the panel has no diff and this
 * shows nothing. The ids and names come from the version, so they are rendered as text only.
 */
@Component({
    selector: 'app-missing-reference-note',
    imports: [WarningNoteComponent],
    template: `
        @for (text of texts(); track $index) {
            <app-warning-note>{{ text }}</app-warning-note>
        }
    `,
    styleUrls: ['./missing-reference-note.component.scss'],
})
export class MissingReferenceNoteComponent {
    /** The fields this note covers (`MissingReference.field`, the path without item keys). */
    readonly fields = input.required<readonly FieldName[]>();

    protected readonly texts = computed(() => {
        const fields: readonly string[] = this.fields();
        const references = this.panelDiff()?.missingReferences ?? [];
        return references.filter((reference) => fields.includes(reference.field)).map(describeMissingReference);
    });

    private readonly panelDiff = inject(NODE_PANEL_DIFF);
}

/** Ids cannot be resolved to names: the entity they named is gone. */
function describeMissingReference(reference: MissingReference): string {
    const missing = reference.missing;
    switch (reference.field as FieldName) {
        case 'python_code.secret_names':
        case 'pre_computation.secret_names':
        case 'post_computation.secret_names':
        case 'telegram_bot_api_key_secret_id':
            return usesNamed('the secret', 'a secret', missing);
        case 'key_value_table':
            return usesNamed('the table', 'a table', missing);
        case 'agent_definition':
            return usesNumbered('agent', 'an agent', missing);
        case 'webhook_trigger':
            return usesNumbered('trigger', 'a trigger', missing);
        case 'subgraph':
            return usesNumbered('flow', 'a flow', missing);
        case 'python_code.venv_id':
            return usesNumbered('venv', 'a venv', missing);
        case 'surface_list':
            return usesNumbered('surface', 'a surface', missing);
        // The warning names the tool's id only, not whether it is a Python or an MCP tool.
        case 'inline_surface':
            return usesNumbered('tool', 'a tool', missing);
        case 'condition_groups[].next_node': {
            const groupName = ROUTE_GROUP_PATH.exec(reference.path)?.[1];
            const group = groupName ? `group ${groupName}` : 'a group';
            return `In this version, ${group} routes to a node that no longer exists.`;
        }
        case 'default_next_node':
            return 'In this version, the default route leads to a node that no longer exists.';
        case 'next_error_node':
            return 'In this version, the error route leads to a node that no longer exists.';
        default:
            return 'This version uses an item that no longer exists.';
    }
}

function usesNamed(withName: string, withoutName: string, missing: number | string | null): string {
    return missing === null
        ? `This version uses ${withoutName} that no longer exists.`
        : `This version uses ${withName} ${missing}; it no longer exists.`;
}

function usesNumbered(kind: string, withoutId: string, missing: number | string | null): string {
    return missing === null
        ? `This version uses ${withoutId} that no longer exists.`
        : `This version uses ${kind} #${missing}; it no longer exists.`;
}
