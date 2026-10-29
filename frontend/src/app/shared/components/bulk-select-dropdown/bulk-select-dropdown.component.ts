import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { Component, computed, effect, ElementRef, input, output, signal, untracked, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

/**
 * The "Select" button of a list's bulk selection, with its one-item "Select All" menu.
 *
 * The host owns select mode and the selection; this only shows them and reports what the user asked for.
 * - Opening the menu (a click on "Select", or the keyboard) enters select mode in the same step.
 * - In select mode it reads "Selected (N)", with an × that clears the selection and leaves select mode;
 *   a click on the label toggles the menu (the design's "Selected_Pressed" state, even at 0).
 * - Only the menu opened by the click that enters select mode keeps the "Select" look (the design's
 *   "Pressed" state) until it closes.
 * - Any change of the selected count closes the menu, so ticking an item closes it.
 */
@Component({
    selector: 'app-bulk-select-dropdown',
    imports: [CdkMenuTrigger, CdkMenu, CdkMenuItem, AppSvgIconComponent, MatTooltipModule],
    templateUrl: './bulk-select-dropdown.component.html',
    styleUrls: ['./bulk-select-dropdown.component.scss'],
})
export class BulkSelectDropdownComponent {
    readonly selectMode = input(false);
    readonly selectedCount = input(0);
    /** Every selectable item is selected; the menu item then reads "Deselect All". */
    readonly allSelected = input(false);
    /** True while the host acts on the selection (a delete in flight). */
    readonly disabled = input(false);
    /** As `app-button`'s: `default` is 40px, level with default buttons; `small` is the designer's 28px component. */
    readonly mod = input<'default' | 'small'>('default');
    /** `filled`: the dark control. `outline`: the look of the flows page's Import button, for the default size. */
    readonly appearance = input<'filled' | 'outline'>('filled');

    readonly selectModeEntered = output<void>();
    readonly selectAllToggled = output<void>();
    readonly cleared = output<void>();

    private readonly menuTrigger = viewChild(CdkMenuTrigger);
    private readonly menuTriggerButton = viewChild.required<CdkMenuTrigger, ElementRef<HTMLButtonElement>>(
        CdkMenuTrigger,
        { read: ElementRef }
    );

    protected readonly isMenuOpen = signal(false);
    /** The open menu is the one that entered select mode: the control keeps the "Select" look until it closes. */
    private readonly isPressedFromDefault = signal(false);
    protected readonly showsSelection = computed(() => this.selectMode() && !this.isPressedFromDefault());
    protected readonly menuItemLabel = computed(() => (this.allSelected() ? 'Deselect All' : 'Select All'));
    protected readonly mainTooltip = computed(() =>
        this.showsSelection() ? `Selected (${this.selectedCount()})` : 'Select'
    );
    protected readonly isSmall = computed(() => this.mod() === 'small');
    protected readonly isOutline = computed(() => this.appearance() === 'outline');
    /** Icon boxes; the sprites draw their glyph inside a transparent inset (see the stylesheet). */
    protected readonly chevronIconSize = computed(() => (this.isSmall() ? '16px' : '20px'));
    protected readonly clearIconSize = computed(() => (this.isSmall() ? '20px' : '24px'));

    private readonly closeMenuOnSelectionChange = effect(() => {
        this.selectedCount();
        untracked(() => this.menuTrigger()?.close());
    });
    private readonly closeMenuOnSelectModeExit = effect(() => {
        if (this.selectMode()) return;
        untracked(() => this.menuTrigger()?.close());
    });

    // 8px below the control, left edges aligned (Figma); right-aligned or above when there is no room.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 8 },
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 8 },
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -8 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -8 },
    ];

    protected onMenuOpened(): void {
        this.isMenuOpen.set(true);
        if (!this.selectMode()) {
            this.isPressedFromDefault.set(true);
            this.selectModeEntered.emit();
        }
    }

    protected onMenuClosed(): void {
        this.isMenuOpen.set(false);
        this.isPressedFromDefault.set(false);
    }

    /** The × goes with the "Selected" look; focus moves to the menu button, which stays on the page. */
    protected onClear(): void {
        this.cleared.emit();
        this.menuTriggerButton().nativeElement.focus();
    }

    /**
     * Escape must close only the menu. CdkMenu closes itself on Escape but lets the event bubble on to the
     * overlay keyboard dispatcher, which hands it to the next overlay down (a dialog hosting the list) and
     * closes that too. So the focused item intercepts Escape first (see `ConfigCardMoreMenuComponent`).
     */
    protected onMenuItemEscape(event: Event): void {
        event.stopPropagation();
        this.menuTrigger()?.close();
        this.menuTriggerButton().nativeElement.focus();
    }
}
