import { Component, computed, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { VenvStatus } from '../../models/venv.model';

interface StatusView {
    label: string;
    icon: string;
    cssClass: string;
}

const STATUS_VIEWS: Record<VenvStatus, StatusView | null> = {
    processing: { label: 'Building', icon: 'loader', cssClass: 'venv-status--processing' },
    failed: { label: 'Failed', icon: 'alert-triangle', cssClass: 'venv-status--failed' },
    declared: { label: 'Queued', icon: 'edit-pencil', cssClass: 'venv-status--declared' },
    completed: null,
};

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

    protected readonly view = computed<StatusView | null>(() => STATUS_VIEWS[this.status()]);
}
