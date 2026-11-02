import { A11yModule } from '@angular/cdk/a11y';
import { Overlay } from '@angular/cdk/overlay';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
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
import { IHeaderAngularComp } from 'ag-grid-angular';
import { Column, GridApi, IHeaderParams } from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { headerBesideColumns, listenForHeaderActivation } from '../shared/header-keyboard.util';
import { OverlayMenuController } from '../shared/overlay-menu.util';

export interface ColumnHeaderMenuParams extends IHeaderParams {
    label?: string;
    colId?: string;
    /** Called when the user clicks "Freeze" or "Unfreeze" */
    onFreezeToggle?: (colId: string) => void;
    /** Called when the user clicks "Hide" */
    onHide?: (colId: string) => void;
    /** Returns true when this column is currently pinned */
    isPinned?: () => boolean;
    /** Whether to show the Freeze/Unfreeze menu item (default: true) */
    showFreeze?: boolean;
    /** Whether to render the chevron button at all (default: true) */
    showChevron?: boolean;
    // For columns that also have a remove icon (field_* / manip_*)
    iconClass?: string;
    tooltip?: string;
    variant?: 'default' | 'delete';
    onIconClick?: (event: MouseEvent) => void;
    showDragGrip?: boolean;
}

@Component({
    selector: 'app-column-header-menu',
    imports: [A11yModule, MatTooltip, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div
            class="chm-wrapper"
            [title]="tooltip"
        >
            @if (label) {
                <span class="chm-label">{{ label }}</span>
            }
            @if (iconClass && onIconClick) {
                <button
                    type="button"
                    [class]="iconClass"
                    [class.chm-icon-clickable]="variant === 'default'"
                    [class.chm-icon-delete]="variant === 'delete'"
                    [attr.aria-label]="tooltip || label"
                    [matTooltip]="tooltip || label || ''"
                    (click)="onIconClick($event)"
                ></button>
            }
            @if (showDragGrip) {
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
            @if (showChevron) {
                <button
                    type="button"
                    #chevronButton
                    class="chm-chevron"
                    (click)="toggleMenu($event)"
                    aria-label="Column options"
                    matTooltip="Column options"
                >
                    <i class="ti ti-chevron-down"></i>
                </button>
            }
        </div>

        <ng-template #menuTemplate>
            <div
                class="chm-dropdown"
                role="menu"
                cdkTrapFocus
                [cdkTrapFocusAutoCapture]="true"
            >
                @if (showFreeze) {
                    <button
                        type="button"
                        role="menuitem"
                        class="chm-menu-item"
                        (click)="handleFreeze()"
                    >
                        @if (isPinned && isPinned()) {
                            <span>Unfreeze All Columns</span>
                        } @else {
                            <span>Freeze Up to This Column</span>
                        }
                    </button>
                }
                <button
                    type="button"
                    role="menuitem"
                    class="chm-menu-item"
                    matTooltip="Hide"
                    (click)="handleHide()"
                >
                    <span>Hide</span>
                </button>
            </div>
        </ng-template>
    `,
    styles: [
        `
            button.chm-menu-item {
                width: 100%;
                border: none;
                font-family: inherit;
                text-align: left;
                outline-offset: -2px;
            }
            button.chm-menu-item:not(:hover, :focus-visible) {
                background: transparent;
            }
            button.chm-menu-item:focus-visible {
                background: var(--purple-alpha-20);
                color: var(--white);
            }
            :host {
                display: block;
                width: 100%;
                height: 100%;
            }

            .chm-wrapper {
                display: flex;
                align-items: center;
                justify-content: space-between;
                width: 100%;
                height: 100%;
                cursor: default;
                gap: 4px;
            }

            .chm-label {
                font-size: 0.875rem;
                color: rgba(255, 255, 255, 0.9);
                font-weight: 500;
                flex: 1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            /* NOTE: kept in sync with .icon-header-clickable in icon-header.component.ts */
            .chm-icon-clickable {
                cursor: pointer;
                background: rgba(104, 95, 255, 0.25);
                border: 1px solid rgba(104, 95, 255, 0.5);
                border-radius: 50%;
                width: 20px;
                height: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 0.75rem !important;
                color: #a89fff !important;
                transition:
                    background 0.15s ease,
                    color 0.15s ease;
                flex-shrink: 0;
            }

            .chm-icon-clickable:is(:hover, :focus-visible) {
                background: rgba(104, 95, 255, 0.5) !important;
                color: #fff !important;
                border-color: var(--accent-color);
            }

            .chm-icon-delete {
                border: none;
                background: none;
                cursor: pointer;
                font-size: 0.8rem !important;
                color: rgba(255, 255, 255, 0.4) !important;
                flex-shrink: 0;
                transition: color 0.15s ease;
                padding: 2px;
            }

            .chm-icon-delete:is(:hover, :focus-visible) {
                color: rgba(255, 100, 100, 0.85) !important;
            }

            .chm-chevron {
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 0;
                border: none;
                background: transparent;
                cursor: pointer;
                color: rgba(255, 255, 255, 0.5);
                border-radius: 3px;
                flex-shrink: 0;
                transition:
                    background 0.15s ease,
                    color 0.15s ease;
            }

            .chm-chevron:hover {
                background: rgba(255, 255, 255, 0.1);
                color: rgba(255, 255, 255, 0.9);
            }

            .chm-chevron i {
                font-size: 0.75rem;
                line-height: 1;
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
        `,
    ],
})
export class ColumnHeaderMenuComponent implements IHeaderAngularComp, OnDestroy {
    @ViewChild('menuTemplate') menuTemplate!: TemplateRef<unknown>;
    private readonly chevronButton = viewChild<ElementRef<HTMLButtonElement>>('chevronButton');

    public label = '';
    public tooltip = '';
    public colId = '';
    public iconClass = '';
    public variant: 'default' | 'delete' = 'default';
    public onIconClick: ((event: MouseEvent) => void) | undefined = undefined;
    public onFreezeToggle: ((colId: string) => void) | undefined = undefined;
    public onHide: ((colId: string) => void) | undefined = undefined;
    public isPinned: (() => boolean) | undefined = undefined;
    public showFreeze = true;
    public showChevron = true;
    public showDragGrip = false;

    private overlay = inject(Overlay);
    private vcr = inject(ViewContainerRef);
    private cdr = inject(ChangeDetectorRef);
    private menuCtrl = new OverlayMenuController(this.overlay, this.vcr);
    private gridApi: GridApi | null = null;
    private column: Column | null = null;
    private stopListeningForActivation: (() => void) | null = null;

    agInit(params: ColumnHeaderMenuParams): void {
        this.gridApi = params.api;
        this.column = params.column;
        // Enter or Space on the focused header opens its menu, as a click on the chevron does.
        // A header without one (a variable column) does nothing: its only control removes
        // the variable and its values, too much for a stray key.
        this.stopListeningForActivation = listenForHeaderActivation(params.eGridHeader, () =>
            this.chevronButton()?.nativeElement.click()
        );
        this.label = params.label || '';
        this.tooltip = params.tooltip || '';
        this.colId = params.colId || params.column?.getColId() || '';
        this.iconClass = params.iconClass || '';
        this.variant = params.variant || 'default';
        this.onIconClick = params.onIconClick;
        this.onFreezeToggle = params.onFreezeToggle;
        this.onHide = params.onHide;
        this.isPinned = params.isPinned;
        this.showFreeze = params.showFreeze !== false;
        this.showChevron = params.showChevron !== false;
        this.showDragGrip = params.showDragGrip === true;
    }

    refresh(_params: ColumnHeaderMenuParams): boolean {
        // Refresh isPinned state so "Freeze"/"Unfreeze" label updates
        if (_params.isPinned) {
            this.isPinned = _params.isPinned;
        }
        if (_params.showFreeze !== undefined) {
            this.showFreeze = _params.showFreeze !== false;
        }
        if (_params.showDragGrip !== undefined) {
            this.showDragGrip = _params.showDragGrip === true;
        }
        if (_params.showChevron !== undefined) {
            this.showChevron = _params.showChevron !== false;
        }
        this.cdr.markForCheck();
        return true;
    }

    toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.menuCtrl.toggle(event.currentTarget as HTMLElement, this.menuTemplate, { closeOnEscape: true });
    }

    handleFreeze(): void {
        this.menuCtrl.close();
        if (this.onFreezeToggle && this.colId) {
            this.onFreezeToggle(this.colId);
            // Freezing moves the header to the other side of the pin line, into a new cell; the focus follows it.
            this.gridApi?.setFocusedHeader(this.colId);
        }
    }

    handleHide(): void {
        this.menuCtrl.close();
        if (this.onHide && this.colId) {
            // The hidden header takes the focus with it; the header beside it gets it instead.
            const next = this.gridApi && this.column ? headerBesideColumns(this.gridApi, [this.column]) : null;
            this.onHide(this.colId);
            if (next) this.gridApi?.setFocusedHeader(next);
        }
    }

    ngOnDestroy(): void {
        this.stopListeningForActivation?.();
        this.menuCtrl.dispose();
    }
}
