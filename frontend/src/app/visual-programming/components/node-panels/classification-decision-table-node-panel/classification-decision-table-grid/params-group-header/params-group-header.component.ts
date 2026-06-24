import { Overlay } from '@angular/cdk/overlay';
import {
    ChangeDetectionStrategy,
    Component,
    inject,
    OnDestroy,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { IHeaderGroupAngularComp } from 'ag-grid-angular';
import { IHeaderGroupParams } from 'ag-grid-community';

import { OverlayMenuController } from '../shared/overlay-menu.util';

export interface ParamsGroupHeaderParams extends IHeaderGroupParams {
    mode?: 'add-only' | 'full';
    onAdd?: (event: MouseEvent) => void;
    onFreeze?: () => void;
    onHide?: () => void;
    isPinned?: () => boolean;
}

@Component({
    selector: 'app-params-group-header',
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div
            class="params-group-header"
            [class.params-group-header--add-only]="mode === 'add-only'"
        >
            <button
                class="add-btn"
                (click)="handleAdd($event)"
                title="Add variable"
            >
                <i class="ti ti-plus"></i>
            </button>
            @if (mode === 'full') {
                <span class="params-label">Params</span>
                <div class="dropdown-wrapper">
                    <button
                        #chevronBtn
                        class="chevron-btn"
                        (click)="toggleMenu($event)"
                        title="Column options"
                    >
                        <i class="ti ti-chevron-down"></i>
                    </button>
                </div>
            }
        </div>

        <ng-template #menuTemplate>
            <div class="params-dropdown">
                <div
                    class="params-dropdown-item"
                    (click)="handleFreeze()"
                >
                    @if (isPinned && isPinned()) {
                        Unfreeze All Columns
                    } @else {
                        Freeze Up to This Column
                    }
                </div>
                <div
                    class="params-dropdown-item"
                    (click)="handleHide()"
                >
                    Hide
                </div>
            </div>
        </ng-template>
    `,
    styles: [
        `
            :host {
                display: block;
                width: 100%;
                height: 100%;
            }
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
                border-color: var(--accent-color);
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
                background: #2a2a2e;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                min-width: 100px;
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
export class ParamsGroupHeaderComponent implements IHeaderGroupAngularComp, OnDestroy {
    @ViewChild('menuTemplate') menuTemplate!: TemplateRef<unknown>;
    @ViewChild('chevronBtn') chevronBtn!: HTMLButtonElement;

    mode: 'add-only' | 'full' = 'full';

    private onAdd: ((event: MouseEvent) => void) | undefined;
    private onFreeze: (() => void) | undefined;
    private onHide: (() => void) | undefined;
    isPinned: (() => boolean) | undefined;

    private overlay = inject(Overlay);
    private vcr = inject(ViewContainerRef);
    private menuCtrl = new OverlayMenuController(this.overlay, this.vcr);

    agInit(params: ParamsGroupHeaderParams): void {
        this.mode = params.mode ?? 'full';
        this.onAdd = params.onAdd;
        this.onFreeze = params.onFreeze;
        this.onHide = params.onHide;
        this.isPinned = params.isPinned;
    }

    refresh(): boolean {
        return true;
    }

    handleAdd(event: MouseEvent): void {
        event.stopPropagation();
        this.onAdd?.(event);
    }

    toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.menuCtrl.toggle(event.currentTarget as HTMLElement, this.menuTemplate);
    }

    handleFreeze(): void {
        this.menuCtrl.close();
        this.onFreeze?.();
    }

    handleHide(): void {
        this.menuCtrl.close();
        this.onHide?.();
    }

    ngOnDestroy(): void {
        this.menuCtrl.dispose();
    }
}
