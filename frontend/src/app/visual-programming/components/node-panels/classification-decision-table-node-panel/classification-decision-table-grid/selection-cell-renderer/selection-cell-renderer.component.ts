import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams, IRowNode } from 'ag-grid-community';

@Component({
    selector: 'app-selection-cell-renderer',
    imports: [],
    template: `
        <div class="selection-cell">
            <span
                class="drag-grip"
                aria-hidden="true"
            >
                <span class="drag-dot"></span>
                <span class="drag-dot"></span>
                <span class="drag-dot"></span>
                <span class="drag-dot"></span>
                <span class="drag-dot"></span>
                <span class="drag-dot"></span>
            </span>
            <div
                class="ag-checkbox-input-wrapper"
                [class.ag-checked]="isSelected"
                (click)="onCheckboxClick($event)"
            >
                <input
                    type="checkbox"
                    class="ag-input-field-input ag-checkbox-input"
                    [checked]="isSelected"
                    (change)="toggleSelection($event)"
                />
            </div>
        </div>
    `,
    styles: [
        `
            :host {
                display: flex;
                align-items: center;
                height: 100%;
            }
            .selection-cell {
                display: flex;
                align-items: center;
                gap: 8px;
                padding-left: 4px;
            }
            .drag-grip {
                display: inline-grid;
                grid-template-columns: repeat(2, 3px);
                grid-template-rows: repeat(3, 3px);
                gap: 2px;
                cursor: grab;
                padding: 4px 2px;
            }
            .drag-grip:active {
                cursor: grabbing;
            }
            .drag-dot {
                width: 3px;
                height: 3px;
                border-radius: 50%;
                background: rgba(217, 217, 222, 0.5);
                pointer-events: none;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SelectionCellRendererComponent implements ICellRendererAngularComp {
    private cdr = inject(ChangeDetectorRef);
    public isSelected = false;
    private node!: IRowNode;
    private gridApi!: ICellRendererParams['api'];

    agInit(params: ICellRendererParams): void {
        this.node = params.node;
        this.gridApi = params.api;
        this.isSelected = !!params.node.isSelected();
        this.gridApi.addEventListener('selectionChanged', this.onSelectionChanged);
    }

    refresh(params: ICellRendererParams): boolean {
        this.node = params.node;
        this.isSelected = !!params.node.isSelected();
        this.cdr.markForCheck();
        return true;
    }

    private onSelectionChanged = (): void => {
        const next = !!this.node.isSelected();
        if (next !== this.isSelected) {
            this.isSelected = next;
            this.cdr.markForCheck();
        }
    };

    public toggleSelection(event: Event): void {
        const checked = (event.target as HTMLInputElement).checked;
        this.node.setSelected(checked);
    }

    public onCheckboxClick(event: MouseEvent): void {
        event.stopPropagation();
    }

    destroy(): void {
        this.gridApi?.removeEventListener('selectionChanged', this.onSelectionChanged);
    }
}
