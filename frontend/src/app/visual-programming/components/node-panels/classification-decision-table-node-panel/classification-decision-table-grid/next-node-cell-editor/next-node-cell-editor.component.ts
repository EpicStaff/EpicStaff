import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    inject,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ICellEditorAngularComp } from 'ag-grid-angular';
import { ICellEditorParams } from 'ag-grid-community';

interface NodeOption {
    label: string;
    value: string;
}

interface NextNodeEditorParams extends ICellEditorParams {
    nodes: NodeOption[];
}

@Component({
    selector: 'app-next-node-cell-editor',
    imports: [CommonModule, FormsModule],
    template: `
        <div class="node-editor-popup" (keydown)="onKeyDown($event)">
            <div class="ne-search">
                <input
                    #searchInput
                    type="text"
                    class="ne-search-input"
                    [(ngModel)]="searchText"
                    (ngModelChange)="filterNodes()"
                    placeholder="Search node..."
                    (keydown.escape)="cancel()"
                />
            </div>
            <div class="ne-list">
                <div
                    *ngFor="let node of filteredNodes"
                    class="ne-item"
                    [class.ne-item-selected]="node.value === value"
                    (click)="selectNode(node.value)"
                >
                    {{ node.label }}
                </div>
                <div *ngIf="filteredNodes.length === 0" class="ne-empty">No nodes found</div>
            </div>
            <div *ngIf="value" class="ne-clear" (click)="clearSelection()"><i class="ti ti-x"></i> Clear</div>
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                position: absolute;
            }
            .node-editor-popup {
                width: 260px;
                max-height: 320px;
                overflow-y: auto;
                background: #1e1e1e;
                border: 1px solid rgba(104, 95, 255, 0.4);
                border-radius: 8px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
                padding: 8px 0;
                display: flex;
                flex-direction: column;
            }
            .ne-search {
                padding: 0 8px 6px;
            }
            .ne-search-input {
                width: 100%;
                background: #141414;
                color: #d4d4d4;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 13px;
                outline: none;
                box-sizing: border-box;
            }
            .ne-search-input:focus {
                border-color: rgba(104, 95, 255, 0.5);
            }
            .ne-list {
                max-height: 220px;
                overflow-y: auto;
            }
            .ne-item {
                padding: 8px 12px;
                font-size: 13px;
                color: #d4d4d4;
                cursor: pointer;
                transition: background 0.1s;
            }
            .ne-item:hover {
                background: rgba(104, 95, 255, 0.12);
            }
            .ne-item-selected {
                background: rgba(104, 95, 255, 0.2) !important;
                border-left: 2px solid #685fff;
            }
            .ne-empty {
                padding: 12px;
                text-align: center;
                color: rgba(255, 255, 255, 0.3);
                font-size: 12px;
            }
            .ne-clear {
                display: flex;
                align-items: center;
                gap: 6px;
                padding: 6px 12px;
                color: rgba(255, 255, 255, 0.4);
                font-size: 12px;
                cursor: pointer;
                border-top: 1px solid rgba(255, 255, 255, 0.08);
                margin-top: 4px;
                transition: background 0.1s;
            }
            .ne-clear:hover {
                background: rgba(255, 255, 255, 0.06);
                color: rgba(255, 255, 255, 0.7);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NextNodeCellEditorComponent implements ICellEditorAngularComp, AfterViewInit {
    @ViewChild('searchInput') searchInput!: ElementRef<HTMLInputElement>;

    private cdr = inject(ChangeDetectorRef);
    private params!: NextNodeEditorParams;

    public value: string = '';
    public searchText: string = '';
    public allNodes: NodeOption[] = [];
    public filteredNodes: NodeOption[] = [];

    agInit(params: NextNodeEditorParams): void {
        this.params = params;
        this.value = params.value || '';
        this.allNodes = params.nodes || [];
        this.filterNodes();
    }

    ngAfterViewInit(): void {
        setTimeout(() => this.searchInput?.nativeElement?.focus(), 50);
    }

    getValue(): string | null {
        return this.value || null;
    }

    isPopup(): boolean {
        return true;
    }
    getPopupPosition(): 'under' {
        return 'under';
    }

    filterNodes(): void {
        const q = (this.searchText || '').toLowerCase().trim();
        this.filteredNodes = q ? this.allNodes.filter((n) => n.label.toLowerCase().includes(q)) : [...this.allNodes];
        this.cdr.markForCheck();
    }

    selectNode(value: string): void {
        this.value = value;
        this.params.stopEditing(false);
    }

    clearSelection(): void {
        this.value = '';
        this.params.stopEditing(false);
    }

    cancel(): void {
        this.params.stopEditing(true);
    }

    onKeyDown(event: KeyboardEvent): void {
        event.stopPropagation();
    }
}
