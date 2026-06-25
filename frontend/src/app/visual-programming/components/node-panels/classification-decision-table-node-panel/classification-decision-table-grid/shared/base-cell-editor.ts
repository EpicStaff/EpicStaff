import { ICellEditorAngularComp } from 'ag-grid-angular';
import { ICellEditorParams } from 'ag-grid-community';

/**
 * Thin abstract base for ag-grid cell editors.
 *
 * Hoisted surface (identical across all CDT cell editors):
 *   - `protected params` field typed to the subclass params type
 *   - `agInit` that stores params (subclasses call super.agInit then do their own work)
 *   - `isPopup()` returning true (both editors are popups)
 *
 * NOT hoisted:
 *   - `getPopupPosition()` — returns 'over' in ExpressionBuilderCellEditor,
 *     'under' in PromptIdCellEditor; stays in each subclass
 *   - `getValue()` — return semantics differ; declared abstract here
 */
export abstract class BaseCellEditor<
    T extends ICellEditorParams = ICellEditorParams,
> implements ICellEditorAngularComp {
    protected params!: T;

    agInit(params: T): void {
        this.params = params;
    }

    isPopup(): boolean {
        return true;
    }

    abstract getValue(): unknown;
}
