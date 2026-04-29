import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { FormGroup, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { SliderWithStepperComponent } from '@shared/components';

@Component({
    selector: 'app-execution-tab',
    templateUrl: './execution-tab.component.html',
    styleUrls: ['../tab.component.scss'],
    imports: [FormsModule, ReactiveFormsModule, SliderWithStepperComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExecutionTabComponent {
    form = input.required<FormGroup>();
}
