import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ICellEditorAngularComp } from 'ag-grid-angular';
import { ICellEditorParams } from 'ag-grid-community';

interface NextNodeOption {
    value: string;
    label: string;
}

interface NextNodeEditorParams extends ICellEditorParams {
    nodes: NextNodeOption[];
}

@Component({
    selector: 'app-next-node-editor',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="next-node-editor-popup">
            <div
                class="nne-list"
                *ngIf="options.length > 0"
            >
                <div
                    *ngFor="let option of options"
                    class="nne-item"
                    [class.nne-item-selected]="option.value === value"
                    (click)="select(option.value)"
                >
                    {{ option.label }}
                </div>
            </div>
            <div
                class="nne-empty"
                *ngIf="options.length === 0"
            >
                No other nodes available
            </div>
            <button
                *ngIf="value"
                type="button"
                class="nne-clear"
                (click)="select('')"
            >
                Clear
            </button>
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                position: absolute;
            }
            .next-node-editor-popup {
                width: 200px;
                background: #212325;
                border: 1px solid #2b2d30;
                border-radius: 10px;
                box-shadow:
                    0px 2px 3px 0px rgba(0, 0, 0, 0.3),
                    0px 6px 10px 4px rgba(0, 0, 0, 0.15);
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            .nne-list {
                display: flex;
                flex-direction: column;
                gap: 6px;
                max-height: 280px;
                overflow-y: auto;
            }
            .nne-item {
                height: 36px;
                background: #2b2d30;
                border: 1px solid rgba(217, 217, 222, 0.16);
                border-radius: 4px;
                padding: 0 12px;
                display: flex;
                align-items: center;
                cursor: pointer;
                flex-shrink: 0;
                font-size: 14px;
                font-family: Inter, sans-serif;
                color: var(--color-text-primary);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .nne-item:hover {
                border-color: rgba(104, 95, 255, 0.4);
            }
            .nne-item-selected {
                border-color: rgba(104, 95, 255, 0.6);
                background: rgba(104, 95, 255, 0.12);
            }
            .nne-empty {
                padding: 12px 0;
                text-align: center;
                font-size: 13px;
                font-family: Inter, sans-serif;
                color: rgba(217, 217, 222, 0.6);
            }
            .nne-clear {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                align-self: flex-start;
                padding: 4px 12px;
                height: 28px;
                background: transparent;
                border: 1px solid var(--accent-color);
                border-radius: 6px;
                color: var(--accent-color);
                font-size: 13px;
                font-family: Inter, sans-serif;
                cursor: pointer;
                box-shadow: none;
                transition: background 0.15s;
            }
            .nne-clear:hover {
                background: rgba(104, 95, 255, 0.08);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NextNodeEditorComponent implements ICellEditorAngularComp {
    private params!: NextNodeEditorParams;

    public value = '';
    public options: NextNodeOption[] = [];

    agInit(params: NextNodeEditorParams): void {
        this.params = params;
        this.value = params.value ?? '';
        this.options = params.nodes ?? [];
    }

    getValue(): string {
        return this.value;
    }

    isPopup(): boolean {
        return true;
    }

    getPopupPosition(): 'under' {
        return 'under';
    }

    select(value: string): void {
        this.value = value;
        this.params.stopEditing(false);
    }
}
