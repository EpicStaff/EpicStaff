import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

/**
 * Thin abstract base for ag-grid cell renderers.
 *
 * Hoisted surface:
 *   - `protected params` field typed to the subclass params type
 *   - `agInit` that stores params (subclasses that need post-init work
 *     call super.agInit(params) then continue)
 *
 * NOT hoisted:
 *   - `refresh()` — all three renderers return true but bodies are fully
 *     component-specific; no shared implementation exists
 *   - `destroy()` — SelectionCellRendererComponent has a meaningful destroy()
 *     that removes an event listener; MonacoCellRendererComponent uses
 *     ngOnDestroy instead; no shared pattern exists
 *
 * Migration status:
 *   - PromptTooltipRendererComponent — migrated (stores params, calls applyParams)
 *   - MonacoCellRendererComponent    — migrated (inherits params field; keeps own agInit)
 *   - SelectionCellRendererComponent — NOT migrated: it extracts params into separate
 *     fields (node, gridApi) and never uses this.params, so super.agInit would store
 *     a reference that is never read; extending would add friction with no reduction.
 */
export abstract class BaseCellRenderer<
    T extends ICellRendererParams = ICellRendererParams,
> implements ICellRendererAngularComp {
    protected params!: T;

    agInit(params: T): void {
        this.params = params;
    }

    abstract refresh(params: T): boolean;
}
