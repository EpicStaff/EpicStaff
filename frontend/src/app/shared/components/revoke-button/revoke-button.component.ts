import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-revoke-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './revoke-button.component.html',
    styleUrls: ['./revoke-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RevokeButtonComponent {
    tooltip = input('Revoke');
    disabled = input(false);

    triggered = output<void>();
}
