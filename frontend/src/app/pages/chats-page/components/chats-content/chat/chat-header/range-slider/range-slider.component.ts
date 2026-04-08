import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

@Component({
    selector: 'app-range-slider',
    standalone: true,
    imports: [CommonModule, FormsModule],
    templateUrl: './range-slider.component.html',
    styleUrls: ['./range-slider.component.scss'],
})
export class RangeSliderComponent {
    @Input() label = '';
    @Input() value = 0;
    @Input() min = 0;
    @Input() max = 100;
    @Input() step = 1;
    @Input() decimals = 0;

    @Output() valueChange = new EventEmitter<number>();

    onValueChange(event: Event): void {
        const input = event.target as HTMLInputElement;
        this.value = parseFloat(input.value);
        this.valueChange.emit(this.value);
    }

    formatValue(): string {
        return this.decimals > 0 ? this.value.toFixed(this.decimals) : this.value.toString();
    }
}
