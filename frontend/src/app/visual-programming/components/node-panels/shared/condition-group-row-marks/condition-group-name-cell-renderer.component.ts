import { Component } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

/** The renderer's own parameter: what a screen reader hears before the name of the row's group, if anything. */
export interface ConditionGroupNameCellParams {
    statusOf: (data: unknown) => string | null;
}

/**
 * The Condition Name cell of a decision table grid on the Changes tab of a version preview: the name, after a status
 * only screen readers hear ("Restore changes this condition. Changed columns: Expression."), since a row's frame and
 * its tooltip are visual only. As text, never HTML.
 */
@Component({
    selector: 'app-condition-group-name-cell',
    template: `@if (status) {
            <span class="visually-hidden">{{ status }} </span>
        }
        {{ name }}`,
})
export class ConditionGroupNameCellRendererComponent implements ICellRendererAngularComp {
    protected name = '';
    protected status: string | null = null;

    agInit(params: ICellRendererParams & ConditionGroupNameCellParams): void {
        this.name = params.valueFormatted ?? String(params.value ?? '');
        this.status = params.statusOf(params.data);
    }

    /** Rendered again: a new status comes with a redraw of the row. */
    refresh(): boolean {
        return false;
    }
}
