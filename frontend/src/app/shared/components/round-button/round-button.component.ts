import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
    selector: 'app-round-button',
    templateUrl: './round-button.component.html',
    styleUrls: ['./round-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RoundButtonComponent {
    label = input.required<string>();
    selected = input(false);
    tooltip = input('');
}
