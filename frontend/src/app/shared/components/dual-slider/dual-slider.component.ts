import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, model, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-dual-slider',
    standalone: true,
    imports: [CommonModule, TooltipComponent, FormsModule],
    templateUrl: './dual-slider.component.html',
    styleUrls: ['./dual-slider.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DualSliderComponent {
    icon = input<string>('help_outline');
    firstLabel = input<string>('');
    firstRequired = input<boolean>(false);
    firstTooltipText = input<string>('');
    secondLabel = input<string>('');
    secondRequired = input<boolean>(false);
    secondTooltipText = input<string>('');
    min = input<number>(0);
    max = input<number>(100);
    step = input<number>(1);
    linked = input<boolean>(false);
    decimals = input<number>(2);

    activeThumb = signal<'left' | 'right'>('left');

    firstValue = model.required<number>();
    secondValue = model.required<number>();

    firstPercentage = computed(() => {
        const val = this.firstValue();
        const minVal = this.min();
        const maxVal = this.max();
        return ((val - minVal) / (maxVal - minVal)) * 100;
    });

    secondPercentage = computed(() => {
        const val = this.secondValue();
        const minVal = this.min();
        const maxVal = this.max();
        return ((val - minVal) / (maxVal - minVal)) * 100;
    });

    firstDisplayValue = computed(() => {
        const val = this.firstValue();
        if (val === null || val === undefined) return '0';
        return val.toFixed(this.decimals());
    });

    secondDisplayValue = computed(() => {
        const val = this.secondValue();
        if (val === null || val === undefined) return '0';
        return val.toFixed(this.decimals());
    });

    updateFirst(newValue: number): void {
        const second = this.secondValue();

        const min = this.min();
        const max = this.max();
        const range = max - min;

        this.firstValue.set(newValue);

        const firstOffset = newValue - min;
        const secondOffset = second - min;

        if (this.linked() || firstOffset + secondOffset > range) {
            const allowedOffset = range - firstOffset;
            this.secondValue.set(min + allowedOffset);
        }
    }

    updateSecond(newValue: number): void {
        const first = this.firstValue();

        const min = this.min();
        const max = this.max();
        const range = max - min;

        this.secondValue.set(newValue);

        const firstOffset = first - min;
        const secondOffset = newValue - min;

        if (this.linked() || firstOffset + secondOffset > range) {
            const allowedOffset = range - secondOffset;
            this.firstValue.set(min + allowedOffset);
        }
    }

    onFirstStepDown(): void {
        const current = this.firstValue();
        const newValue = Math.max(this.min(), current - this.step());
        this.updateFirst(this.roundToDecimals(newValue));
    }

    onFirstStepUp(): void {
        const current = this.firstValue();
        const newValue = Math.min(this.max(), current + this.step());
        this.updateFirst(this.roundToDecimals(newValue));
    }

    onSecondStepDown(): void {
        const current = this.firstValue();
        const newValue = Math.max(this.min(), current - this.step());
        this.updateSecond(this.roundToDecimals(newValue));
    }

    onSecondStepUp(): void {
        const current = this.firstValue();
        const newValue = Math.min(this.max(), current + this.step());
        this.updateSecond(this.roundToDecimals(newValue));
    }

    private roundToDecimals(value: number): number {
        const factor = Math.pow(10, this.decimals());
        return Math.round(value * factor) / factor;
    }
}
