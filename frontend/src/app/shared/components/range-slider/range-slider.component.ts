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
    @Output() change = new EventEmitter<number>();

    private currentValue: number = this.value;

    onSliderMove(value: number) {
        this.currentValue = value;
        this.value = value;
        this.valueChange.emit(value);
    }

    onSliderEnd() {
        this.change.emit(this.currentValue);
    }

    formatValue(): string {
        return this.decimals > 0 ? this.value.toFixed(this.decimals) : this.value.toString();
    }
}
