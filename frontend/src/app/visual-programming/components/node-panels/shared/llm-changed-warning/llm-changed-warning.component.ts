import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
    selector: 'app-llm-changed-warning',
    templateUrl: './llm-changed-warning.component.html',
    styleUrls: ['./llm-changed-warning.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmChangedWarningComponent {
    readonly visible = input.required<boolean>();
}
