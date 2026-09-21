import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons/button/button.component';

@Component({
    selector: 'app-fetch-error-state',
    imports: [AppSvgIconComponent, ButtonComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './fetch-error-state.component.html',
    styleUrls: ['./fetch-error-state.component.scss'],
})
export class FetchErrorStateComponent {
    public readonly title = input.required<string>();
    public readonly message = input<string>('Check your connection and try again.');
    public readonly retryLabel = input<string>('Retry');
    public readonly retry = output<void>();
}
