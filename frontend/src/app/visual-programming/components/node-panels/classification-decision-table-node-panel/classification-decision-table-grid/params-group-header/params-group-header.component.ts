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
import { MatTooltip } from '@angular/material/tooltip';
import { IHeaderGroupAngularComp } from 'ag-grid-angular';
import { Column, GridApi, IHeaderGroupParams } from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { headerBesideColumns, listenForHeaderActivation } from '../shared/header-keyboard.util';
import { OverlayMenuController } from '../shared/overlay-menu.util';

export interface ParamsGroupHeaderParams extends IHeaderGroupParams {
    mode?: 'add-only' | 'full';
    ownerLabel?: string;
    onAdd?: (event: MouseEvent) => void;
    onFreeze?: () => void;
    onHide?: () => void;
    isPinned?: () => boolean;
}

@Component({
    selector: 'app-params-group-header',
    imports: [A11yModule, MatTooltip, AppSvgIconComponent],
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
                    matTooltip="Add variable"
                    (click)="handleAddFromMenu()"
                >
                    Add variable
                </button>
                <button
                    type="button"
                    role="menuitem"
                    class="params-dropdown-item"
                    (click)="handleFreeze()"
                >
                    @if (isPinned && isPinned()) {
                        Unfreeze All Columns
                    } @else {
                        Freeze Up to This Column
                    }
                </button>
                <button
                    type="button"
                    role="menuitem"
                    class="params-dropdown-item"
                    matTooltip="Hide"
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
    private onFreeze: (() => void) | undefined;
    private onHide: (() => void) | undefined;
    isPinned: (() => boolean) | undefined;

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

    handleAddFromMenu(): void {
        this.menuCtrl.close();
        // The + button anchors the picker, as when it is clicked.
        this.addButton()?.nativeElement.click();
    }

    toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.menuCtrl.toggle(event.currentTarget as HTMLElement, this.menuTemplate, { closeOnEscape: true });
    }

    handleFreeze(): void {
        this.menuCtrl.close();
        this.onFreeze?.();
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
