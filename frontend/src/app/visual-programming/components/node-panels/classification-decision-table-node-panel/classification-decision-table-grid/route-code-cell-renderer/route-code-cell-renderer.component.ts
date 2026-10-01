import { ChangeDetectionStrategy, Component, computed, signal } from '@angular/core';
import { HelpTooltipComponent } from '@shared/components';
import { ICellRendererParams } from 'ag-grid-community';

import { ConditionGroup } from '../../../../../core/models/decision-table.model';
import { CDT_ROUTE_CONTINUE_COPY } from '../../cdt.constants';
import { isRouteCodeIgnored, isRouteContinueConflict } from '../../cdt-route-continue.util';
import { BaseCellRenderer } from '../shared/base-cell-renderer';

/**
 * What the Route Code cell flags about its row; null when there is nothing to flag.
 *
 * - `route-ignored`: a route code wired to nothing with Continue ticked. Continue
 *   applies, so the code is dimmed and a muted warning icon explains why.
 * - `conflict`: a route code wired to a node with Continue ticked. The cell border
 *   turns red (grid `cellClassRules`) and a red icon says how to fix it.
 *
 * A row with neither a route code nor Continue is marked by the red border alone.
 */
export interface RouteCodeCellStatus {
    readonly kind: 'route-ignored' | 'conflict';
    readonly icon: string;
    readonly message: string;
    readonly iconWidth: string;
    readonly iconHeight: string;
}

/** The route_code column's params: rows are condition groups, values are route codes. */
export interface RouteCodeCellParams extends ICellRendererParams<ConditionGroup, string> {
    /** Whether the row's route code leads to a canvas node; the grid answers from live flow state. */
    readonly routeHasTarget: (row: ConditionGroup | undefined) => boolean;
}

export function routeCodeCellStatus(
    row: ConditionGroup | null | undefined,
    routeHasTarget: boolean
): RouteCodeCellStatus | null {
    if (isRouteContinueConflict(row, routeHasTarget)) {
        return {
            kind: 'conflict',
            icon: 'alert-triangle',
            message: CDT_ROUTE_CONTINUE_COPY.routeContinueConflict,
            iconWidth: '16px',
            iconHeight: '16px',
        };
    }
    if (isRouteCodeIgnored(row, routeHasTarget)) {
        // The design's thin warning glyph; its viewBox is 16 x 14, so it renders non-square.
        return {
            kind: 'route-ignored',
            icon: 'thin-warning',
            message: CDT_ROUTE_CONTINUE_COPY.routeCodeIgnored,
            iconWidth: '16px',
            iconHeight: '14px',
        };
    }
    return null;
}

/**
 * The Route Code cell: the code, plus a status icon when the row's route code
 * and Continue collide (see `RouteCodeCellStatus`). The icon is always visible
 * and its tooltip opens with no delay, unlike ag-grid's own cell tooltip.
 *
 * Display only: no click handlers, so double-click and typing still reach
 * ag-grid and open the text editor.
 *
 * The tooltip opens to the left, away from the Continue column that sits
 * immediately to the right of this cell. Icon colours live in the grid's scss,
 * because `app-help-tooltip` paints its icon itself.
 */
@Component({
    selector: 'app-route-code-cell-renderer',
    imports: [HelpTooltipComponent],
    template: `
        <div class="cdt-route-code-cell">
            <span
                class="cdt-route-code-cell__code"
                [class.cdt-route-code-cell__code--ignored]="isCodeIgnored()"
                >{{ code() }}</span
            >
            @if (status(); as current) {
                <span
                    class="cdt-route-code-cell__status"
                    [class.cdt-route-code-cell__status--conflict]="isConflict()"
                    role="img"
                    [attr.aria-label]="current.message"
                >
                    <app-help-tooltip
                        [text]="current.message"
                        [icon]="current.icon"
                        position="left"
                        [width]="current.iconWidth"
                        [height]="current.iconHeight"
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
            /* The code has no effect while Continue applies. */
            .cdt-route-code-cell__code--ignored {
                color: var(--transparent-white-16);
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
    protected readonly isCodeIgnored = computed(() => this.status()?.kind === 'route-ignored');
    protected readonly isConflict = computed(() => this.status()?.kind === 'conflict');

    override agInit(params: RouteCodeCellParams): void {
        super.agInit(params);
        this.applyParams(params);
    }

    /** Called on `refreshCells`: after a Continue change, and when the table's connections change. */
    refresh(params: RouteCodeCellParams): boolean {
        this.params = params;
        this.applyParams(params);
        return true;
    }

    private applyParams(params: RouteCodeCellParams): void {
        this.code.set(params.value ?? '');
        this.status.set(routeCodeCellStatus(params.data, params.routeHasTarget(params.data)));
    }
}
