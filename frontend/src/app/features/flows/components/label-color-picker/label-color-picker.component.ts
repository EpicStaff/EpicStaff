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

import { getLabelColorOption, LABEL_COLOR_OPTIONS, LabelColor, LabelColorOption } from '../../models/label.model';

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
    readonly panelStyle = signal<Record<string, string>>({});
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
            const trigger = this.elementRef.nativeElement.querySelector('.color-trigger-btn') as HTMLElement;
            if (trigger) {
                const rect = trigger.getBoundingClientRect();
                const spaceBelow = window.innerHeight - rect.bottom;
                const openUpward = spaceBelow < 220; // panel is ~210px tall (6 options)
                this.openUpward.set(openUpward);
                const left = rect.left + rect.width / 2;
                if (openUpward) {
                    this.panelStyle.set({
                        top: 'auto',
                        bottom: window.innerHeight - rect.top + 4 + 'px',
                        left: left + 'px',
                    });
                } else {
                    this.panelStyle.set({
                        top: rect.bottom + 4 + 'px',
                        bottom: 'auto',
                        left: left + 'px',
                    });
                }
            }
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
