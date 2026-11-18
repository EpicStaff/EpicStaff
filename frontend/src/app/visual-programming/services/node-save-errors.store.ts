import { Injectable, Signal, signal } from '@angular/core';
import { NodeType } from '@shared/models';

import { NodeModel } from '../core/models/node.model';
import { SaveErrorsByNodeId, SaveFieldError } from '../utils/save/bulk-save-errors';

/** A field a panel shows its save errors under, through `fieldMessages`; `list` for a field of a child row. */
interface FieldShownByPanel {
    readonly field: string;
    readonly list?: string;
}

/**
 * The template fields shown under the field itself. The panel shell lists every other save error of the node.
 * A classification table's prompt text also shows under the field, but it sits in a collapsed card of another
 * tab, so the shell lists it too. That shell entry stays until the next save, even once the text is fixed: only the
 * copy under the field hides on an edit.
 */
const FIELD_SHOWN_BY_PANEL: Partial<Record<NodeType, FieldShownByPanel>> = {
    [NodeType.TASK]: { field: 'instructions' },
    [NodeType.KNOWLEDGE_RETRIEVER]: { field: 'query' },
    [NodeType.AGENT]: { list: 'tasks', field: 'instructions' },
};

const NO_ERRORS: readonly SaveFieldError[] = [];
const NO_MESSAGES: readonly string[] = [];

/**
 * What the backend refused in the nodes of the last bulk save, per canvas node id, until a save goes through.
 * Kept off the node models, so it never reaches the diff or the dirty check.
 */
@Injectable({
    providedIn: 'root',
})
export class NodeSaveErrorsStore {
    private readonly errorsSignal = signal<SaveErrorsByNodeId>(new Map());
    public readonly errors: Signal<SaveErrorsByNodeId> = this.errorsSignal.asReadonly();

    /** A full save was refused: its errors replace those of every node. */
    public setAll(errors: SaveErrorsByNodeId): void {
        if (errors.size === 0 && this.errorsSignal().size === 0) return;
        this.errorsSignal.set(errors);
    }

    /** A one-node save answered: `errors` are that node's now (none once it saved). */
    public setForNode(nodeId: string, errors: readonly SaveFieldError[]): void {
        if (errors.length === 0 && !this.errorsSignal().has(nodeId)) return;
        this.errorsSignal.update((current) => {
            const next = new Map(current);
            if (errors.length > 0) {
                next.set(nodeId, errors);
            } else {
                next.delete(nodeId);
            }
            return next;
        });
    }

    /** A save went through, or another graph loaded (canvas ids are minted per load). */
    public clear(): void {
        this.setAll(new Map());
    }

    /**
     * The messages of one field while it still holds what was sent: an edit hides them, and putting the
     * refused value back shows them again. `child` picks a row of a child list (`tasks`, `prompt_configs`).
     */
    public fieldMessages(
        nodeId: string,
        field: string,
        currentValue: unknown,
        child?: { list: string; key: string }
    ): readonly string[] {
        const matching = (this.errorsSignal().get(nodeId) ?? NO_ERRORS).filter(
            (error) =>
                error.field === field &&
                error.child?.list === child?.list &&
                error.child?.key === child?.key &&
                error.sentValue === currentValue
        );
        return matching.length > 0 ? matching.flatMap((error) => error.messages) : NO_MESSAGES;
    }

    /** The node's errors no panel shows under a field (see `FIELD_SHOWN_BY_PANEL`). */
    public nodeLevelErrors(node: NodeModel): readonly SaveFieldError[] {
        const errors = this.errorsSignal().get(node.id) ?? NO_ERRORS;
        const shownByPanel = FIELD_SHOWN_BY_PANEL[node.type];
        if (!shownByPanel) return errors;
        return errors.filter((error) => error.field !== shownByPanel.field || error.child?.list !== shownByPanel.list);
    }
}
