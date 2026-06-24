import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams, IRowNode } from 'ag-grid-community';

@Component({
    selector: 'app-selection-cell-renderer',
    imports: [CommonModule],
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
            <label
                class="selection-checkbox"
                (click)="onCheckboxClick($event)"
            >
                <input
                    type="checkbox"
                    [checked]="isSelected"
                    (change)="toggleSelection($event)"
                />
                <span class="checkmark"></span>
            </label>
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
            .selection-checkbox {
                position: relative;
                width: 16px;
                height: 16px;
                cursor: pointer;
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }
            .selection-checkbox input {
                position: absolute;
                opacity: 0;
                width: 16px;
                height: 16px;
                margin: 0;
                cursor: pointer;
            }
            .checkmark {
                display: block;
                width: 16px;
                height: 16px;
                border: 1px solid rgba(217, 217, 222, 0.5);
                border-radius: 3px;
                background: transparent;
                transition:
                    background 0.15s ease,
                    border-color 0.15s ease;
            }
            .selection-checkbox input:checked + .checkmark {
                background: var(--purple-primary);
                border-color: var(--purple-primary);
            }
            .selection-checkbox input:checked + .checkmark::after {
                content: '';
                position: absolute;
                left: 5px;
                top: 2px;
                width: 4px;
                height: 8px;
                border: solid #fff;
                border-width: 0 2px 2px 0;
                transform: rotate(45deg);
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
