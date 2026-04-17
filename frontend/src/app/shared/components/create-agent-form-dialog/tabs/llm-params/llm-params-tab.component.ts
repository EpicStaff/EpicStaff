import { ChangeDetectionStrategy, Component, input } from "@angular/core";
import { FormGroup, ReactiveFormsModule } from "@angular/forms";
import { SliderWithStepperComponent } from "@shared/components";

@Component({
    selector: 'app-llm-params-tab',
    templateUrl: './llm-params-tab.component.html',
    styleUrls: ['../tab.component.scss'],
    imports: [
        ReactiveFormsModule,
        SliderWithStepperComponent
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class LlmParamsTabComponent {
    form = input.required<FormGroup>();
}
