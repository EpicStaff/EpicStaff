import { Component, computed, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { VENV_STATUS_VIEWS, VenvStatus, VenvStatusView } from '../../models/venv.model';

@Component({
    selector: 'app-venv-status-badge',
    imports: [MatTooltipModule, AppSvgIconComponent],
    template: `
        @if (view(); as view) {
            <span
                class="venv-status text-body-small-large"
                [class]="view.cssClass"
                [matTooltip]="error() ?? ''"
                [matTooltipDisabled]="!error()"
                matTooltipPosition="above"
            >
                <app-svg-icon
                    class="venv-status__icon"
                    [icon]="view.icon"
                    size="14px"
                />
                {{ view.label }}
            </span>
        }
    `,
    styleUrls: ['./venv-status-badge.component.scss'],
})
export class VenvStatusBadgeComponent {
    readonly status = input.required<VenvStatus>();
    readonly error = input<string | null>(null);

    protected readonly view = computed<VenvStatusView | null>(() => VENV_STATUS_VIEWS[this.status()]);
}
