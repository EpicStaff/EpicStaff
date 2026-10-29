import { CdkConnectedOverlay, CdkOverlayOrigin, ConnectedPosition } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    inject,
    Input,
    OnChanges,
    output,
    signal,
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

    private readonly elementRef = inject(ElementRef);

    readonly isOpen = signal<boolean>(false);
    readonly colorOptions = LABEL_COLOR_OPTIONS;
    /** Below the trigger, centered; above it when there is no room below. */
    readonly positions: ConnectedPosition[] = [
        { originX: 'center', originY: 'bottom', overlayX: 'center', overlayY: 'top', offsetY: 4 },
        { originX: 'center', originY: 'top', overlayX: 'center', overlayY: 'bottom', offsetY: -4 },
    ];
    currentOption: LabelColorOption = getLabelColorOption(LabelColor.Default);

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

    select(option: LabelColorOption, event: MouseEvent): void {
        event.stopPropagation();
        this.currentOption = option;
        this.colorChange.emit(option.id);
        this.isOpen.set(false);
    }
}
