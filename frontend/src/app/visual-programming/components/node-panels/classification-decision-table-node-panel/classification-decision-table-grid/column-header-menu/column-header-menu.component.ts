import { Overlay } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    inject,
    OnDestroy,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { IHeaderAngularComp } from 'ag-grid-angular';
import { IHeaderParams } from 'ag-grid-community';

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
}

@Component({
    selector: 'app-column-header-menu',
    standalone: true,
    imports: [CommonModule],
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
                <i
                    [class]="iconClass"
                    [class.chm-icon-clickable]="variant === 'default'"
                    [class.chm-icon-delete]="variant === 'delete'"
                    (click)="onIconClick($event)"
                ></i>
            }
            @if (showChevron) {
                <button
                    class="chm-chevron"
                    (click)="toggleMenu($event)"
                    title="Column options"
                >
                    <i class="ti ti-chevron-down"></i>
                </button>
            }
        </div>

        <ng-template #menuTemplate>
            <div class="chm-dropdown">
                @if (showFreeze) {
                    <div
                        class="chm-menu-item"
                        (click)="handleFreeze()"
                    >
                        @if (isPinned && isPinned()) {
                            <span>Unfreeze All Columns</span>
                        } @else {
                            <span>Freeze Up to This Column</span>
                        }
                    </div>
                }
                <div
                    class="chm-menu-item"
                    (click)="handleHide()"
                >
                    <span>Hide</span>
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

            .chm-wrapper {
                display: flex;
                align-items: center;
                justify-content: space-between;
                width: 100%;
                height: 100%;
                cursor: default;
                gap: var(--space-2xs);
                padding: 0 var(--space-2xs);
            }

            .chm-label {
                font-size: var(--font-size-md);
                color: var(--white-alpha-90);
                font-weight: var(--font-weight-medium);
                flex: 1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            /* NOTE: kept in sync with .icon-header-clickable in icon-header.component.ts */
            .chm-icon-clickable {
                cursor: pointer;
                background: var(--purple-alpha-25);
                border: 1px solid var(--purple-alpha-50);
                border-radius: 50%;
                width: 20px;
                height: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: var(--font-size-xs) !important;
                color: #a89fff !important;
                transition:
                    background 0.15s ease,
                    color 0.15s ease;
                flex-shrink: 0;
            }

            .chm-icon-clickable:hover {
                background: var(--purple-alpha-50) !important;
                color: var(--white) !important;
                border-color: var(--accent-color);
            }

            .chm-icon-delete {
                cursor: pointer;
                font-size: var(--font-size-sm) !important;
                color: var(--white-alpha-40) !important;
                flex-shrink: 0;
                transition: color 0.15s ease;
                padding: var(--space-3xs);
            }

            .chm-icon-delete:hover {
                color: rgba(255, 100, 100, 0.85) !important;
            }

            .chm-chevron {
                display: flex;
                align-items: center;
                justify-content: center;
                width: 18px;
                height: 18px;
                padding: 0;
                border: none;
                background: transparent;
                cursor: pointer;
                color: var(--white-alpha-50);
                border-radius: var(--radius-sm);
                flex-shrink: 0;
                transition:
                    background 0.15s ease,
                    color 0.15s ease;
            }

            .chm-chevron:hover {
                background: var(--white-alpha-10);
                color: var(--white-alpha-90);
            }

            .chm-chevron i {
                font-size: var(--font-size-xs);
                line-height: 1;
            }
        `,
    ],
})
export class ColumnHeaderMenuComponent implements IHeaderAngularComp, OnDestroy {
    @ViewChild('menuTemplate') menuTemplate!: TemplateRef<unknown>;

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

    private overlay = inject(Overlay);
    private vcr = inject(ViewContainerRef);
    private cdr = inject(ChangeDetectorRef);
    private menuCtrl = new OverlayMenuController(this.overlay, this.vcr);

    agInit(params: ColumnHeaderMenuParams): void {
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
    }

    refresh(_params: ColumnHeaderMenuParams): boolean {
        // Refresh isPinned state so "Freeze"/"Unfreeze" label updates
        if (_params.isPinned) {
            this.isPinned = _params.isPinned;
        }
        if (_params.showFreeze !== undefined) {
            this.showFreeze = _params.showFreeze !== false;
        }
        if (_params.showChevron !== undefined) {
            this.showChevron = _params.showChevron !== false;
        }
        this.cdr.markForCheck();
        return true;
    }

    toggleMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.menuCtrl.toggle(event.currentTarget as HTMLElement, this.menuTemplate);
    }

    handleFreeze(): void {
        this.menuCtrl.close();
        if (this.onFreezeToggle && this.colId) {
            this.onFreezeToggle(this.colId);
        }
    }

    handleHide(): void {
        this.menuCtrl.close();
        if (this.onHide && this.colId) {
            this.onHide(this.colId);
        }
    }

    ngOnDestroy(): void {
        this.menuCtrl.dispose();
    }
}
