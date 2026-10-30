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

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CdtFreezeMenuItem, CdtFreezeSide } from '../shared/column-freeze.util';
import { OverlayMenuController } from '../shared/overlay-menu.util';

export interface ParamsGroupHeaderParams extends IHeaderGroupParams {
    mode?: 'add-only' | 'full';
    ownerLabel?: string;
    onAdd?: (event: MouseEvent) => void;
    onFreezeToggle?: (side: CdtFreezeSide) => void;
    onHide?: () => void;
    /** True while the group anchors the freeze; hides the drag grip. */
    isPinned?: () => boolean;
    /** The freeze items as they stand when the menu opens */
    getFreezeMenuItems?: () => CdtFreezeMenuItem[];
}

@Component({
    selector: 'app-params-group-header',
    imports: [AppSvgIconComponent],
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
                <span class="params-label"
                    >Params
                    @if (ownerLabel) {
                        <span class="params-owner">&nbsp;({{ ownerLabel }})</span>
                    }
                </span>
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
                @if (!(isPinned && isPinned())) {
                    <span
                        class="drag-grip-btn"
                        title="Drag to reposition"
                    >
                        <app-svg-icon
                            icon="drag-grip"
                            size="12px"
                        />
                    </span>
                }
            }
        </div>

        <ng-template #menuTemplate>
            <div class="params-dropdown">
                @for (item of freezeMenuItems; track item.side) {
                    <div
                        class="params-dropdown-item"
                        [class.params-dropdown-item--disabled]="item.disabledReason"
                        [attr.title]="item.disabledReason"
                        [attr.aria-disabled]="item.disabledReason ? true : null"
                        (click)="handleFreeze(item)"
                    >
                        {{ item.label }}
                    </div>
                }
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
                font-size: 0.875rem;
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
                font-size: 0.875rem;
                color: rgba(255, 255, 255, 0.9);
                font-weight: 500;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                min-width: 0;
            }
            .params-owner {
                font-size: 12px;
                font-weight: 500;
                color: var(--color-ks-transparent-text-60);
            }
            .drag-grip-btn {
                display: none;
                align-items: center;
                justify-content: center;
                width: 24px;
                height: 28px;
                border-radius: 4px;
                flex-shrink: 0;
                cursor: grab;
                color: var(--color-ks-transparent-text-60);
                transition: background 0.15s ease;
            }
            :host-context(.ag-header-cell-moving) .drag-grip-btn {
                display: inline-flex;
            }
            .drag-grip-btn:hover {
                background: var(--color-ghost-btn-hover);
                color: var(--color-ks-transparent-text-80);
            }
            .drag-grip-btn:active {
                cursor: grabbing;
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
                font-size: 0.8125rem;
                color: rgba(255, 255, 255, 0.85);
                cursor: pointer;
                white-space: nowrap;
            }
            .params-dropdown-item:hover {
                background: rgba(104, 95, 255, 0.2);
            }
            .params-dropdown-item--disabled,
            .params-dropdown-item--disabled:hover {
                background: transparent;
                color: var(--color-text-disabled);
                cursor: not-allowed;
            }
        `,
    ],
})
export class ParamsGroupHeaderComponent implements IHeaderGroupAngularComp, OnDestroy {
    @ViewChild('menuTemplate') menuTemplate!: TemplateRef<unknown>;
    @ViewChild('chevronBtn') chevronBtn!: HTMLButtonElement;

    mode: 'add-only' | 'full' = 'full';
    ownerLabel = '';
    private onAdd: ((event: MouseEvent) => void) | undefined;
    private onFreezeToggle: ((side: CdtFreezeSide) => void) | undefined;
    private onHide: (() => void) | undefined;
    private getFreezeMenuItems: (() => CdtFreezeMenuItem[]) | undefined;
    isPinned: (() => boolean) | undefined;
    freezeMenuItems: CdtFreezeMenuItem[] = [];

    private overlay = inject(Overlay);
    private vcr = inject(ViewContainerRef);
    private menuCtrl = new OverlayMenuController(this.overlay, this.vcr);

    agInit(params: ParamsGroupHeaderParams): void {
        this.mode = params.mode ?? 'full';
        this.ownerLabel = params.ownerLabel ?? '';
        this.onAdd = params.onAdd;
        this.onFreezeToggle = params.onFreezeToggle;
        this.onHide = params.onHide;
        this.isPinned = params.isPinned;
        this.getFreezeMenuItems = params.getFreezeMenuItems;
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
        this.freezeMenuItems = this.getFreezeMenuItems?.() ?? [];
        this.menuCtrl.toggle(event.currentTarget as HTMLElement, this.menuTemplate);
    }

    handleFreeze(item: CdtFreezeMenuItem): void {
        if (item.disabledReason) return;
        this.menuCtrl.close();
        this.onFreezeToggle?.(item.side);
    }

    handleHide(): void {
        this.menuCtrl.close();
        this.onHide?.();
    }

    ngOnDestroy(): void {
        this.menuCtrl.dispose();
    }
}
