import { Component, computed, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { VenvStatus } from '../../models/venv.model';

interface StatusView {
    label: string;
    cssClass: string;
}

const STATUS_VIEWS: Record<VenvStatus, StatusView> = {
    processing: { label: 'Building', cssClass: 'venv-status--processing' },
    completed: { label: 'Ready', cssClass: 'venv-status--completed' },
    failed: { label: 'Failed', cssClass: 'venv-status--failed' },
    declared: { label: 'Queued', cssClass: 'venv-status--declared' },
};

@Component({
    selector: 'app-venv-status-badge',
    imports: [MatTooltipModule],
    template: `
        <span
            class="venv-status"
            [class]="view().cssClass"
            [matTooltip]="error() ?? ''"
            [matTooltipDisabled]="!error()"
            matTooltipPosition="above"
        >
            {{ view().label }}
        </span>
    `,
    styleUrls: ['./venv-status-badge.component.scss'],
})
export class VenvStatusBadgeComponent {
    readonly status = input.required<VenvStatus>();
    readonly error = input<string | null>(null);

    protected readonly view = computed<StatusView>(() => STATUS_VIEWS[this.status()]);
}
