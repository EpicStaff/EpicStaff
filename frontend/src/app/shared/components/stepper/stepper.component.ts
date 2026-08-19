import { NgClass, NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-stepper',
    imports: [NgClass, NgStyle, AppSvgIconComponent],
    templateUrl: './stepper.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./stepper.component.scss'],
})
export class StepperComponent {
    steps = input<string[]>([]);

    currentStep = input<number>(0);
}
