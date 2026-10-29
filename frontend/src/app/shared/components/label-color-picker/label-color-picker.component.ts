import { FocusableOption, FocusKeyManager } from '@angular/cdk/a11y';
import { CdkConnectedOverlay, CdkOverlayOrigin, ConnectedPosition } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    inject,
    Injector,
    Input,
    OnChanges,
    output,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
import { getLabelColorOption, LABEL_COLOR_OPTIONS, LabelColor, LabelColorOption } from '@shared/models';

@Component({
    selector: 'app-label-color-picker',
    imports: [CommonModule, CdkConnectedOverlay, CdkOverlayOrigin],
    templateUrl: './label-color-picker.component.html',
    styleUrls: ['./label-color-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LabelColorPickerComponent implements OnChanges {
    @Input() selectedColor: LabelColor = LabelColor.Default;
    colorChange = output<LabelColor>();

    private readonly triggerButton = viewChild.required<ElementRef<HTMLButtonElement>>('triggerButton');
    private readonly optionButtons = viewChildren<ElementRef<HTMLButtonElement>>('optionButton');

    readonly isOpen = signal<boolean>(false);
    readonly colorOptions = LABEL_COLOR_OPTIONS;
    /** Below the trigger, centered; above it when there is no room below. */
    readonly positions: ConnectedPosition[] = [
        { originX: 'center', originY: 'bottom', overlayX: 'center', overlayY: 'top', offsetY: 4 },
        { originX: 'center', originY: 'top', overlayX: 'center', overlayY: 'bottom', offsetY: -4 },
    ];
    currentOption: LabelColorOption = getLabelColorOption(LabelColor.Default);

    private readonly elementRef = inject(ElementRef);
    /** Up/Down (wrapping) and Home/End walk the options while the panel is open. */
    private readonly keyManager = new FocusKeyManager<FocusableOption>(
        computed(() =>
            this.optionButtons().map(({ nativeElement }) => ({
                // The panel is focused before its first positioning; scrolling to it then would jump the page.
                focus: () => nativeElement.focus({ preventScroll: true }),
            }))
        ),
        inject(Injector)
    )
        .withWrap()
        .withHomeAndEnd();

    ngOnChanges(): void {
        this.currentOption = getLabelColorOption(this.selectedColor);
    }

    /** The trigger is outside the overlay too; its own click toggles, so it is skipped here. */
    onOutsideClick(event: MouseEvent): void {
        if (!this.elementRef.nativeElement.contains(event.target)) {
            this.isOpen.set(false);
        }
    }

    toggle(event: MouseEvent): void {
        event.stopPropagation();
        this.isOpen.update((v) => !v);
    }

    select(option: LabelColorOption, event: Event): void {
        event.stopPropagation();
        this.currentOption = option;
        this.closeToTrigger();
        // After focus is back on the trigger, so a consumer may move it on (e.g. to its name input).
        this.colorChange.emit(option.id);
    }

    /** The panel is in an overlay, outside the trigger's DOM: it takes focus on open, on the current color. */
    protected onPanelAttached(): void {
        const selectedIndex = this.colorOptions.findIndex((option) => option.id === this.currentOption.id);
        this.keyManager.setActiveItem(Math.max(selectedIndex, 0));
    }

    /**
     * Keys while open (the overlay receives them wherever focus is): arrows and Home/End move between
     * options, Enter/Space pick the focused one, Escape and Tab close back to the trigger.
     * The overlay closes itself on Escape.
     */
    protected onPanelKeydown(event: KeyboardEvent): void {
        if (event.key === 'Escape') {
            this.triggerButton().nativeElement.focus();
            return;
        }
        // Tab goes on from the trigger, as if the panel were right after it.
        if (event.key === 'Tab') {
            this.closeToTrigger();
            return;
        }
        const focusedIndex = this.optionButtons().findIndex(
            ({ nativeElement }) => nativeElement === document.activeElement
        );
        if (event.key === 'Enter' || event.key === ' ') {
            if (focusedIndex < 0) return;
            event.preventDefault();
            this.select(this.colorOptions[focusedIndex], event);
            return;
        }
        this.keyManager.updateActiveItem(focusedIndex);
        this.keyManager.onKeydown(event);
    }

    private closeToTrigger(): void {
        this.triggerButton().nativeElement.focus();
        this.isOpen.set(false);
    }
}
