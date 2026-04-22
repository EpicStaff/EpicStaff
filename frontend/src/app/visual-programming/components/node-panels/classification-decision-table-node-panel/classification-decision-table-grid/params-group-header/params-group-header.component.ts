import { ChangeDetectionStrategy, Component, HostListener, signal } from '@angular/core';
import { IHeaderGroupAngularComp } from 'ag-grid-angular';
import { IHeaderGroupParams } from 'ag-grid-community';

@Component({
    selector: 'app-params-group-header',
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="params-group-header" [class.params-group-header--add-only]="mode === 'add-only'">
            <button class="add-btn" (click)="handleAdd($event)" title="Add variable">
                <i class="ti ti-plus"></i>
            </button>
            @if (mode === 'full') {
                <span class="params-label">Params</span>
                <div class="dropdown-wrapper">
                    <button class="chevron-btn" (click)="toggleDropdown($event)" title="Column options">
                        <i class="ti ti-chevron-down"></i>
                    </button>
                </div>
            }
            @if (showDropdown() && dropdownPos()) {
                <div
                    class="params-dropdown"
                    [style.top.px]="dropdownPos()!.top"
                    [style.left.px]="dropdownPos()!.left"
                    (click)="$event.stopPropagation()"
                >
                    <div class="params-dropdown-item" (click)="handleFreeze()">Freeze</div>
                    <div class="params-dropdown-item" (click)="handleHide()">Hide</div>
                </div>
            }
        </div>
    `,
    styles: [
        `
            .params-group-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 6px;
                width: 100%;
                height: 100%;
                padding: 0 4px;
                position: relative;
            }
            .params-group-header--add-only {
                justify-content: space-between;
            }
            .add-btn {
                background: #27272b;
                border: 1px solid rgba(104, 95, 255, 0.5);
                border-radius: 4px;
                width: 16px;
                height: 16px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                color: #a89fff;
                font-size: 0.75rem;
                padding: 0;
                flex-shrink: 0;
                transition: background 0.15s ease;
            }
            .add-btn:hover {
                background: rgba(104, 95, 255, 0.5);
                color: #fff;
                border-color: #685fff;
            }
            .chevron-btn {
                cursor: pointer;
                color: rgba(255, 255, 255, 0.5);
                background: none;
                border: none;
                padding: 0 2px;
                font-size: 0.85rem;
                flex-shrink: 0;
                display: flex;
                align-items: center;
                transition: color 0.15s ease;
            }
            .chevron-btn:hover {
                color: rgba(255, 255, 255, 0.9);
            }
            .params-label {
                flex: 1;
                font-size: 0.85rem;
                color: rgba(255, 255, 255, 0.9);
                font-weight: 500;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .dropdown-wrapper {
            }
            .params-dropdown {
                position: fixed;
                background: #2a2a2e;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                min-width: 100px;
                z-index: 9999;
                overflow: hidden;
                box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
            }
            .params-dropdown-item {
                padding: 8px 14px;
                font-size: 13px;
                color: rgba(255, 255, 255, 0.85);
                cursor: pointer;
                white-space: nowrap;
            }
            .params-dropdown-item:hover {
                background: rgba(104, 95, 255, 0.2);
            }
        `,
    ],
})
export class ParamsGroupHeaderComponent implements IHeaderGroupAngularComp {
    showDropdown = signal(false);
    dropdownPos = signal<{ top: number; left: number } | null>(null);
    mode: 'add-only' | 'full' = 'full';

    private onAdd: ((event: MouseEvent) => void) | undefined;
    private onFreeze: (() => void) | undefined;
    private onHide: (() => void) | undefined;

    agInit(
        params: IHeaderGroupParams & {
            mode?: 'add-only' | 'full';
            onAdd?: (event: MouseEvent) => void;
            onFreeze?: () => void;
            onHide?: () => void;
        }
    ): void {
        this.mode = params.mode ?? 'full';
        this.onAdd = params.onAdd;
        this.onFreeze = params.onFreeze;
        this.onHide = params.onHide;
    }

    refresh(): boolean {
        return true;
    }

    handleAdd(event: MouseEvent): void {
        event.stopPropagation();
        this.onAdd?.(event);
    }

    toggleDropdown(event: MouseEvent): void {
        event.stopPropagation();
        const isOpen = this.showDropdown();
        if (!isOpen) {
            const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
            this.dropdownPos.set({ top: rect.bottom + 4, left: rect.left });
        } else {
            this.dropdownPos.set(null);
        }
        this.showDropdown.set(!isOpen);
    }

    handleFreeze(): void {
        this.onFreeze?.();
        this.showDropdown.set(false);
        this.dropdownPos.set(null);
    }

    handleHide(): void {
        this.onHide?.();
        this.showDropdown.set(false);
        this.dropdownPos.set(null);
    }

    @HostListener('document:click')
    onDocumentClick(): void {
        if (this.showDropdown()) {
            this.showDropdown.set(false);
            this.dropdownPos.set(null);
        }
    }
}
