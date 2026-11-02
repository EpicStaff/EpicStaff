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
    ViewContainerRef,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { IHeaderAngularComp } from 'ag-grid-angular';
import { IHeaderParams } from 'ag-grid-community';

import { listenForHeaderActivation } from '../shared/header-keyboard.util';
import { OverlayMenuController } from '../shared/overlay-menu.util';

export type EnableFilterMode = 'all' | 'enabled' | 'disabled';

interface EnableFilterHeaderParams extends IHeaderParams {
    getMode: () => EnableFilterMode;
    setMode: (mode: EnableFilterMode) => void;
}

@Component({
    selector: 'app-enable-filter-header',
    imports: [A11yModule, MatTooltip, AppSvgIconComponent],
    template: `
        <div class="enable-header">
            <span class="enable-label">{{ label }}</span>
            <button
                type="button"
                #anchor
                class="enable-filter-btn"
                [class.active]="mode !== 'enabled'"
                (click)="openMenu()"
                aria-label="Filter rows"
                matTooltip="Filter rows"
            >
                <app-svg-icon
                    icon="filter-rows"
                    size="14px"
                ></app-svg-icon>
            </button>
        </div>

        <ng-template #menuTemplate>
            <div
                class="ef-dropdown"
                role="menu"
                cdkTrapFocus
                [cdkTrapFocusAutoCapture]="true"
            >
                <button
                    type="button"
                    role="menuitemradio"
                    class="ef-item"
                    matTooltip="Enable/Disable"
                    [class.selected]="mode === 'all'"
                    [attr.aria-checked]="mode === 'all'"
                    (click)="select('all')"
                >
                    Enable/Disable
                </button>
                <button
                    type="button"
                    role="menuitemradio"
                    class="ef-item"
                    matTooltip="Only Enable"
                    [class.selected]="mode === 'enabled'"
                    [attr.aria-checked]="mode === 'enabled'"
                    (click)="select('enabled')"
                >
                    Only Enable
                </button>
                <button
                    type="button"
                    role="menuitemradio"
                    class="ef-item"
                    matTooltip="Only Disable"
                    [class.selected]="mode === 'disabled'"
                    [attr.aria-checked]="mode === 'disabled'"
                    (click)="select('disabled')"
                >
                    Only Disable
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
            .enable-header {
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 4px;
                width: 100%;
                height: 100%;
            }
            .enable-label {
                color: rgba(255, 255, 255, 0.9);
                font-size: 0.875rem;
                font-weight: 500;
            }
            .enable-filter-btn {
                width: 18px;
                height: 18px;
                padding: 0;
                border: none;
                background: transparent;
                color: rgba(255, 255, 255, 0.6);
                cursor: pointer;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                transition: color 0.15s ease;
            }
            .enable-filter-btn:hover {
                color: var(--purple-primary);
            }
            .ef-dropdown {
                background: #212325;
                border: 1px solid #2b2d30;
                border-radius: 8px;
                padding: 4px;
                box-shadow: var(--shadow-raised);
                min-width: 160px;
            }
            .ef-item {
                display: block;
                width: 100%;
                padding: 8px 12px;
                border: none;
                background: none;
                font-family: inherit;
                font-size: 0.8125rem;
                text-align: left;
                color: var(--color-text-primary);
                border-radius: 4px;
                cursor: pointer;
                user-select: none;
            }
            .ef-item:is(:hover, :focus-visible) {
                background: rgba(255, 255, 255, 0.04);
            }
            .ef-item.selected {
                color: var(--purple-primary);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EnableFilterHeaderComponent implements IHeaderAngularComp, OnDestroy {
    private overlay = inject(Overlay);
    private vcr = inject(ViewContainerRef);
    private cdr = inject(ChangeDetectorRef);

    @ViewChild('anchor', { read: ElementRef, static: true }) anchorEl!: ElementRef<HTMLElement>;
    @ViewChild('menuTemplate', { static: true }) menuTemplate!: TemplateRef<unknown>;

    public label = 'Enable';
    public mode: EnableFilterMode = 'enabled';
    private params!: EnableFilterHeaderParams;
    private menuCtrl = new OverlayMenuController(this.overlay, this.vcr);
    private stopListeningForActivation: (() => void) | null = null;

    agInit(params: EnableFilterHeaderParams): void {
        this.params = params;
        // Enter or Space on the focused header opens the filter menu, as a click on its button does.
        this.stopListeningForActivation = listenForHeaderActivation(params.eGridHeader, () => this.openMenu());
        this.mode = params.getMode();
        this.label = this.labelForMode(this.mode);
    }

    refresh(params: EnableFilterHeaderParams): boolean {
        this.params = params;
        this.mode = params.getMode();
        this.label = this.labelForMode(this.mode);
        this.cdr.markForCheck();
        return true;
    }

    // Config that reproduces enable-filter-header's original single-position,
    // no-withPush behaviour (distinct from the two-position default used by
    // column-header-menu and params-group-header).
    private readonly menuCfg = { withFlipFallback: false, withPush: false, closeOnEscape: true };

    public openMenu(): void {
        this.menuCtrl.toggle(this.anchorEl.nativeElement, this.menuTemplate, this.menuCfg);
    }

    public select(mode: EnableFilterMode): void {
        // Closed first, so the focus is back on the header when `setMode` rebuilds the
        // header row: ag-grid then carries it over to the new header cell instead of
        // dropping it on <body>, where Delete would delete the selected flow node.
        this.menuCtrl.close();
        this.mode = mode;
        this.label = this.labelForMode(mode);
        this.cdr.markForCheck();
        this.params.setMode(mode);
    }

    private labelForMode(mode: EnableFilterMode): string {
        switch (mode) {
            case 'all':
                return 'En/Dis';
            case 'disabled':
                return 'Disable';
            default:
                return 'Enable';
        }
    }

    ngOnDestroy(): void {
        this.stopListeningForActivation?.();
        this.menuCtrl.dispose();
    }
}
