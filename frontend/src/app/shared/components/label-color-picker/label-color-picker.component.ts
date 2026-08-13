import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    HostListener,
    inject,
    Input,
    OnChanges,
    output,
    signal,
} from '@angular/core';
import { getLabelColorOption, LABEL_COLOR_OPTIONS, LabelColor, LabelColorOption } from '@shared/models';

@Component({
    selector: 'app-label-color-picker',
    imports: [CommonModule],
    templateUrl: './label-color-picker.component.html',
    styleUrls: ['./label-color-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LabelColorPickerComponent implements OnChanges {
    @Input() selectedColor: LabelColor = LabelColor.Default;
    colorChange = output<LabelColor>();

    private readonly elementRef = inject(ElementRef);

    readonly isOpen = signal<boolean>(false);
    readonly openUpward = signal<boolean>(false);
    readonly colorOptions = LABEL_COLOR_OPTIONS;
    currentOption: LabelColorOption = getLabelColorOption(LabelColor.Default);

    ngOnChanges(): void {
        this.currentOption = getLabelColorOption(this.selectedColor);
    }

    @HostListener('document:click', ['$event'])
    onDocumentClick(event: MouseEvent): void {
        if (!this.elementRef.nativeElement.contains(event.target)) {
            this.isOpen.set(false);
        }
    }

    toggle(event: MouseEvent): void {
        event.stopPropagation();
        const willOpen = !this.isOpen();
        if (willOpen) {
            const rect = this.elementRef.nativeElement.getBoundingClientRect();
            const spaceBelow = window.innerHeight - rect.bottom;
            this.openUpward.set(spaceBelow < 220);
        }
        this.isOpen.update((v) => !v);
    }

    select(option: LabelColorOption, event: MouseEvent): void {
        event.stopPropagation();
        this.currentOption = option;
        this.colorChange.emit(option.id);
        this.isOpen.set(false);
    }
}
