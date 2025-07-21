import {
  Component,
  Input,
  Output,
  EventEmitter,
  OnChanges,
  SimpleChanges,
} from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-form-slider',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './form-slider.component.html',
  styleUrls: ['./form-slider.component.scss'],
})
export class FormSliderComponent implements OnChanges {
  @Input() value: number = 50;
  @Input() label: string = '';
  @Input() min: number = 0;
  @Input() max: number = 100;
  @Input() step: number = 1;
  @Input() valueFormat: 'none' | 'percent' | 'decimal' = 'none';

  @Output() valueChange = new EventEmitter<number>();

  valuePosition: string = '50%';

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['value'] || changes['min'] || changes['max']) {
      this.updateValuePosition();
    }
  }

  onSliderInput(event: Event): void {
    const newValue = Number((event.target as HTMLInputElement).value);
    this.value = newValue;
    this.updateValuePosition();
    this.valueChange.emit(newValue);
  }

  private updateValuePosition(): void {
    const percentage = ((this.value - this.min) / (this.max - this.min)) * 100;
    this.valuePosition = `${percentage}%`;
  }

  // Format the value if needed (e.g. to add % or other units)
  getFormattedValue(): string {
    switch (this.valueFormat) {
      case 'percent':
        return `${this.value}%`;
      case 'decimal':
        // If value is from 0-100, display as 0.00-1.00
        if (this.min === 0 && this.max === 100) {
          return (this.value / 100).toFixed(2);
        }
        return this.value.toFixed(2);
      default:
        return `${this.value}`;
    }
  }
}
