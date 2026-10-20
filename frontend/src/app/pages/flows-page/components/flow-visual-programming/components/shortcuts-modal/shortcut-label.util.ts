import { ShortcutParams } from '@shared/models';

import { ACTION_PARAMS, EDITOR_ACTIONS } from '../../../../../../visual-programming/core/keymap/editor-actions';
import { flowIdOf } from '../../../../../../visual-programming/core/keymap/shortcut-params';
import { ChordHolder } from '../../../../../../visual-programming/core/keymap/shortcut-resolution';

export interface ShortcutLabel {
    readonly text: string;
    readonly isMuted: boolean;
}

export interface FlowLookup {
    readonly names: ReadonlyMap<number, string>;
    readonly currentFlowId: number | null;
}

const ACTION_LABELS: ReadonlyMap<string, string> = new Map(EDITOR_ACTIONS.map((action) => [action.id, action.label]));

export function actionLabel(action: string): string {
    return ACTION_LABELS.get(action) ?? action;
}

export function flowLabel(flowId: number, flows: FlowLookup): string | null {
    const flowName = flows.names.get(flowId);
    if (flowName === undefined) {
        return null;
    }
    return flowId === flows.currentFlowId ? `${flowName} (this flow)` : flowName;
}

export function shortcutLabel(action: string, params: ShortcutParams | undefined, flows: FlowLookup): ShortcutLabel {
    const label = actionLabel(action);
    switch (ACTION_PARAMS.get(action)) {
        case 'flow': {
            const flowId = flowIdOf(params);
            const name = flowId === null ? null : flowLabel(flowId, flows);
            return name === null
                ? { text: `${label}: Flow not available`, isMuted: true }
                : { text: `${label}: ${name}`, isMuted: flowId === flows.currentFlowId };
        }
        case undefined:
            return { text: label, isMuted: false };
    }
}

export function takenByMessage(holder: ChordHolder, keys: string, flows: FlowLookup): string {
    if (holder.source === 'custom') {
        return `Already used by your ${shortcutLabel(holder.action, holder.params, flows).text} shortcut`;
    }
    return `${keys} is already ${actionLabel(holder.action)}'s key`;
}
