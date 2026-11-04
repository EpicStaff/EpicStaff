import { A11yModule } from '@angular/cdk/a11y';
import { Overlay } from '@angular/cdk/overlay';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    inject,
    OnDestroy,
    TemplateRef,
    ViewChild,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { IHeaderGroupAngularComp } from 'ag-grid-angular';
import { Column, GridApi, IHeaderGroupParams } from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CdtFreezeMenuItem, CdtFreezeSide } from '../shared/column-freeze.util';
import { headerBesideColumns, listenForHeaderActivation } from '../shared/header-keyboard.util';
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
    imports: [A11yModule, AppSvgIconComponent, MatTooltipModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div
            class="params-group-header"
            [class.params-group-header--add-only]="mode === 'add-only'"
        >
            <button
                type="button"
                #addBtn
                class="add-btn"
                (click)="handleAdd($event)"
                aria-label="Add variable"
                matTooltip="Add variable"
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
                        type="button"
                        #chevronBtn
                        class="chevron-btn"
                        (click)="toggleMenu($event)"
                        aria-label="Column options"
                        matTooltip="Column options"
                    >
                        <i class="ti ti-chevron-down"></i>
                    </button>
                </div>
                @if (!(isPinned && isPinned())) {
                    <span
                        class="drag-grip-btn"
                        matTooltip="Drag to reposition"
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
            <div
                class="params-dropdown"
                role="menu"
                cdkTrapFocus
                [cdkTrapFocusAutoCapture]="true"
            >
                <!-- The header cell takes Enter and Space for this menu, so the + button is reached from here. -->
                <button
                    type="button"
                    role="menuitem"
                    class="params-dropdown-item"
                    (click)="handleAddFromMenu()"
                >
                    Add variable
                </button>
                @for (item of freezeMenuItems; track item.side) {
                    <button
                        type="button"
                        role="menuitem"
                        class="params-dropdown-item"
                        [class.params-dropdown-item--disabled]="item.disabledReason"
                        [attr.title]="item.disabledReason"
                        [attr.aria-disabled]="item.disabledReason ? true : null"
                        (click)="handleFreeze(item)"
                    >
                        {{ item.label }}
                    </button>
                }
                <button
                    type="button"
                    role="menuitem"
                    class="params-dropdown-item"
                    (click)="handleHide()"
                >
                    Hide
                </button>
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
                display: block;
                width: 100%;
                padding: 8px 14px;
                border: none;
                background: none;
                font-family: inherit;
                font-size: 0.8125rem;
                text-align: left;
                color: rgba(255, 255, 255, 0.85);
                cursor: pointer;
                white-space: nowrap;
                // The dropdown clips its overflow: the ring is drawn inside.
                outline-offset: -2px;
            }
            .params-dropdown-item:is(:hover, :focus-visible) {
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
    private readonly addButton = viewChild<ElementRef<HTMLButtonElement>>('addBtn');
    private readonly chevronButton = viewChild<ElementRef<HTMLButtonElement>>('chevronBtn');

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
    private gridApi: GridApi | null = null;
    private groupId = '';
    private leafColumns: () => Column[] = () => [];
    private stopListeningForActivation: (() => void) | null = null;

    agInit(params: ParamsGroupHeaderParams): void {
        this.gridApi = params.api;
        this.groupId = params.columnGroup.getGroupId();
        this.leafColumns = () => params.columnGroup.getDisplayedLeafColumns();
        // Enter or Space on the focused header does what a click on its main button does:
        // opens the column menu, or the variable picker when there is no menu.
        this.stopListeningForActivation = listenForHeaderActivation(params.eGridHeader, () =>
            (this.chevronButton() ?? this.addButton())?.nativeElement.click()
        );
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

    handleAddFromMenu(): void {
        this.menuCtrl.close();
        // The + button anchors the picker, as when it is clicked.
        this.addButton()?.nativeElement.click();
    }

    toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.freezeMenuItems = this.getFreezeMenuItems?.() ?? [];
        this.menuCtrl.toggle(event.currentTarget as HTMLElement, this.menuTemplate, { closeOnEscape: true });
    }

    handleFreeze(item: CdtFreezeMenuItem): void {
        if (item.disabledReason) return;
        this.menuCtrl.close();
        this.onFreezeToggle?.(item.side);
        // Freezing moves the header to the other side of the pin line, into a new cell; the focus follows it.
        this.gridApi?.setFocusedHeader(this.groupId);
    }

    handleHide(): void {
        this.menuCtrl.close();
        // The hidden group takes the focus with it; the header beside it gets it instead.
        const next = this.gridApi ? headerBesideColumns(this.gridApi, this.leafColumns()) : null;
        this.onHide?.();
        if (next) this.gridApi?.setFocusedHeader(next);
    }

    ngOnDestroy(): void {
        this.stopListeningForActivation?.();
        this.menuCtrl.dispose();
    }
}
