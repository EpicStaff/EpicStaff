import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { HelpTooltipComponent } from '@shared/components';
import { ICellRendererParams } from 'ag-grid-community';

import { ConditionGroup } from '../../../../../core/models/decision-table.model';
import { CDT_ROUTE_CONTINUE_COPY } from '../../cdt.constants';
import { isContinueIgnored } from '../../cdt-route-continue.util';
import { BaseCellRenderer } from '../shared/base-cell-renderer';

/**
 * What the Route Code cell flags about its row; null when there is nothing to flag.
 *
 * Only a row whose Continue is ignored gets an icon. A row with neither a route
 * code nor Continue is marked by the red cell border alone.
 */
export interface RouteCodeCellStatus {
    readonly icon: string;
    readonly message: string;
}

/** The route_code column's params: rows are condition groups, values are route codes. */
type RouteCodeCellParams = ICellRendererParams<ConditionGroup, string>;

export function routeCodeCellStatus(row: ConditionGroup | null | undefined): RouteCodeCellStatus | null {
    return isContinueIgnored(row) ? { icon: 'alert-triangle', message: CDT_ROUTE_CONTINUE_COPY.continueIgnored } : null;
}

/**
 * The Route Code cell: the code, plus a status icon when the row's Continue is
 * ignored because a route code is set. The icon is always visible and its
 * tooltip opens with no delay, unlike ag-grid's own cell tooltip.
 *
 * Display only: no click handlers, so double-click and typing still reach
 * ag-grid and open the text editor.
 *
 * The tooltip opens to the left, away from the Continue column that sits
 * immediately to the right of this cell.
 */
@Component({
    selector: 'app-route-code-cell-renderer',
    imports: [HelpTooltipComponent],
    template: `
        <div class="cdt-route-code-cell">
            <span class="cdt-route-code-cell__code">{{ code() }}</span>
            @if (status(); as current) {
                <span
                    class="cdt-route-code-cell__status"
                    role="img"
                    [attr.aria-label]="current.message"
                >
                    <app-help-tooltip
                        [text]="current.message"
                        [icon]="current.icon"
                        position="left"
                        size="16px"
                    />
                </span>
            }
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                width: 100%;
                height: 100%;
            }
            .cdt-route-code-cell {
                display: flex;
                align-items: center;
                gap: 6px;
                width: 100%;
                height: 100%;
                min-width: 0;
            }
            .cdt-route-code-cell__code {
                flex: 1;
                min-width: 0;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .cdt-route-code-cell__status {
                display: inline-flex;
                flex-shrink: 0;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RouteCodeCellRendererComponent extends BaseCellRenderer<RouteCodeCellParams> {
    protected readonly code = signal('');
    protected readonly status = signal<RouteCodeCellStatus | null>(null);

    override agInit(params: RouteCodeCellParams): void {
        super.agInit(params);
        this.applyParams(params);
    }

    /** Called on `refreshCells`, including after the Continue cell changes. */
    refresh(params: RouteCodeCellParams): boolean {
        this.params = params;
        this.applyParams(params);
        return true;
    }

    private applyParams(params: RouteCodeCellParams): void {
        this.code.set(params.value ?? '');
        this.status.set(routeCodeCellStatus(params.data));
    }
}
