import { Component } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

import { isCellTextTruncated } from './condition-group-row-marks';

/** The renderer's own parameters. */
export interface ConditionGroupNameCellParams {
    /** What a screen reader hears before the name of the row's group, if anything. */
    statusOf: (data: unknown) => string | null;
    /** Whether the row tooltip shows over the row's name cell; read when a tooltip is about to open. */
    showsRowTooltip: (data: unknown) => boolean;
}

/**
 * The Condition Name cell of a decision table grid on the Changes tab of a version preview: the name, after a status
 * only screen readers hear ("Restore changes this condition. Changed columns: Expression."), since a row's frame and
 * its tooltip are visual only. As text, never HTML.
 *
 * A cut-off name shows in full in a tooltip, as in the live editor (ag-grid's, `tooltipShowMode: 'whenTruncated'`); a
 * custom renderer has to say when, since ag-grid cannot see inside it. Not where the row tooltip shows: one tooltip at
 * a time, and the row tooltip carries the full name.
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
        params.setTooltip(
            this.name,
            () => !params.showsRowTooltip(params.data) && isCellTextTruncated(params.eGridCell)
        );
    }

    /** Rendered again: a new status comes with a redraw of the row. */
    refresh(): boolean {
        return false;
    }
}
