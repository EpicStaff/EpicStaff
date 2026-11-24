import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons/button/button.component';
import { Spinner2Component } from '../spinner-type2/spinner.component';

@Component({
    selector: 'app-fetch-error-state',
    imports: [AppSvgIconComponent, ButtonComponent, Spinner2Component],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './fetch-error-state.component.html',
    styleUrls: ['./fetch-error-state.component.scss'],
})
export class FetchErrorStateComponent {
    public readonly title = input.required<string>();
    public readonly message = input<string>('Check your connection and try again.');
    /** A line under the message, e.g. why a retry may not help at once; none when `null`. */
    public readonly hint = input<string | null>(null);
    public readonly retryLabel = input<string>('Retry');
    /** A retry is under way: the button stays focusable but inactive, and a spinner shows next to it. */
    public readonly busy = input<boolean>(false);
    public readonly mod = input<'default' | 'small'>('default');
    public readonly retry = output<void>();
}
