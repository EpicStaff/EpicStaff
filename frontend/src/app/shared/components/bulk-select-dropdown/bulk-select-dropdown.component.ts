import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import {
    afterNextRender,
    Component,
    computed,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

/**
 * The "Select" button of a list's bulk selection, with its one-item "Select All" menu.
 *
 * The host owns select mode and the selection; this only shows them and reports what the user asked for.
 * - Opening the menu (a click on "Select", or the keyboard) enters select mode in the same step.
 * - In select mode it reads "Selected (N)", with an × that clears the selection and leaves select mode;
 *   a click on the label toggles the menu (the design's "Selected_Pressed" state, even at 0).
 * - The `toolbar` look differs: with nothing selected it is a plain toggle (no chevron, no menu) that enters
 *   select mode and, clicked again, leaves it; the menu and the × come only with a selection. Its menu has two
 *   fixed items: "Select All" (off once all is selected) and "Clear Selection" (`selectionCleared`).
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
    /**
     * `filled`: the dark control. `outline`: the look of the flows page's Import button, for the default size.
     * `toolbar`: the LLM Library toolbar, for the default size: transparent, a check-square icon before the label,
     * and "Select (N)" (not "Selected") in the Selected states. The menu is the `filled` one.
     */
    readonly appearance = input<'filled' | 'outline' | 'toolbar'>('filled');
    /**
     * With `toolbar`, shows the icon in place of the word "Select", which stays the name (the tooltip says it too):
     * the icon alone at rest, the icon, count and chevron in the Selected states.
     */
    readonly iconOnly = input(false);

    readonly selectModeEntered = output<void>();
    readonly selectAllToggled = output<void>();
    readonly cleared = output<void>();
    /** Toolbar look: "Clear Selection" in the menu; unlike the ×, select mode stays on. */
    readonly selectionCleared = output<void>();

    private readonly menuTrigger = viewChild(CdkMenuTrigger);
    /** The menu trigger, or the select-mode toggle that stands in for it (toolbar look, nothing selected). */
    private readonly mainButton = viewChild.required<ElementRef<HTMLButtonElement>>('mainButton');

    protected readonly isMenuOpen = signal(false);
    /** The open menu is the one that entered select mode: the control keeps the "Select" look until it closes. */
    private readonly isPressedFromDefault = signal(false);
    /** In the toolbar look the Selected states need a selection: at 0 it is the plain "Select" toggle again. */
    protected readonly showsSelection = computed(
        () =>
            this.selectMode() &&
            !this.isPressedFromDefault() &&
            (this.appearance() !== 'toolbar' || this.selectedCount() > 0)
    );
    protected readonly menuItemLabel = computed(() => (this.allSelected() ? 'Deselect All' : 'Select All'));
    protected readonly isSmall = computed(() => this.mod() === 'small');
    protected readonly isOutline = computed(() => this.appearance() === 'outline');
    protected readonly isToolbar = computed(() => this.appearance() === 'toolbar');
    protected readonly isIconOnly = computed(() => this.isToolbar() && this.iconOnly());
    /** Toolbar look with nothing selected: a plain toggle of select mode, with no chevron and no menu. */
    protected readonly isSelectToggle = computed(() => this.isToolbar() && !this.showsSelection());
    protected readonly selectionWord = computed(() => (this.isToolbar() ? 'Select' : 'Selected'));
    protected readonly mainTooltip = computed(() =>
        this.showsSelection() ? `${this.selectionWord()} (${this.selectedCount()})` : 'Select'
    );
    /** Icon boxes; the sprites draw their glyph inside a transparent inset (see the stylesheet). */
    protected readonly chevronIconSize = computed(() => (this.isSmall() ? '16px' : '20px'));
    protected readonly clearIconSize = computed(() => (this.isSmall() ? '20px' : '24px'));

    private readonly injector = inject(Injector);

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

    /** Focuses the menu trigger, or the select-mode toggle in its place. */
    public focus(): void {
        this.mainButton().nativeElement.focus();
    }

    /** The first click enters select mode; a second, with nothing selected, leaves it. */
    protected onToggleSelectMode(): void {
        if (this.selectMode()) {
            this.cleared.emit();
        } else {
            this.selectModeEntered.emit();
        }
    }

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
        // "Deselect All" in the toolbar look swaps the trigger for the toggle once the host has the new count:
        // the focus the menu gave back to the trigger then goes with it, so the toggle takes it.
        if (this.isToolbar()) {
            afterNextRender(
                () => {
                    if (document.activeElement === document.body) this.mainButton().nativeElement.focus();
                },
                { injector: this.injector }
            );
        }
    }

    /** The × goes with the "Selected" look; focus moves to the menu button, which stays on the page. */
    protected onClear(): void {
        this.cleared.emit();
        this.focusMainButton();
    }

    /**
     * Escape must close only the menu. CdkMenu closes itself on Escape but lets the event bubble on to the
     * overlay keyboard dispatcher, which hands it to the next overlay down (a dialog hosting the list) and
     * closes that too. So the focused item intercepts Escape first (see `ConfigCardMoreMenuComponent`).
     */
    protected onMenuItemEscape(event: Event): void {
        event.stopPropagation();
        this.menuTrigger()?.close();
        this.focusMainButton();
    }

    /** In the toolbar look the next render may swap the trigger for the toggle: that one gets the focus then. */
    private focusMainButton(): void {
        this.mainButton().nativeElement.focus();
        if (this.isToolbar()) {
            afterNextRender(() => this.mainButton().nativeElement.focus(), { injector: this.injector });
        }
    }
}
