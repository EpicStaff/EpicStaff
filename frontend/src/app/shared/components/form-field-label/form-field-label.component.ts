import {
    Component,
    input,
    ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HelpTooltipComponent } from '../help-tooltip/help-tooltip.component';

@Component({
    selector: 'app-form-field-label',
    standalone: true,
    imports: [CommonModule, HelpTooltipComponent],
    templateUrl: './form-field-label.component.html',
    styleUrls: ['./form-field-label.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FormFieldLabelComponent {
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
}
