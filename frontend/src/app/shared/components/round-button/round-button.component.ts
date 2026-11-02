import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

@Component({
    selector: 'app-round-button',
    imports: [MatTooltip],
    templateUrl: './round-button.component.html',
    styleUrls: ['./round-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RoundButtonComponent {
    label = input.required<string>();
    selected = input(false);
    /** Shown on hover and focus, and the button's accessible name in place of its short label. */
    tooltip = input('');
}
