import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { GraphSessionStatus } from '../../services/flows-sessions.service';

@Component({
    selector: 'app-flow-session-status-badge',
    standalone: true,
    imports: [CommonModule],
    template: `
        <span
            class="status-badge"
            [ngClass]="statusClass"
        >
            <i [class]="statusIcon"></i>
            {{ statusLabel }}
        </span>
    `,
    styleUrls: ['./flow-session-status-badge.component.scss'],
})
export class FlowSessionStatusBadgeComponent {
    @Input() status!: GraphSessionStatus;

    get statusLabel(): string {
        switch (this.status) {
            case GraphSessionStatus.RUNNING:
                return 'Running';
            case GraphSessionStatus.ERROR:
                return 'Error';
            case GraphSessionStatus.ENDED:
                return 'Completed';
            case GraphSessionStatus.WAITING_FOR_USER:
                return 'Waiting';
            case GraphSessionStatus.PENDING:
                return 'Pending';
            case GraphSessionStatus.EXPIRED:
                return 'Expired';
            case GraphSessionStatus.STOP:
                return 'Stopped';
            default:
                return 'Unknown';
        }
    }

    get statusClass(): string {
        switch (this.status) {
            case GraphSessionStatus.RUNNING:
                return 'status-running';
            case GraphSessionStatus.ERROR:
                return 'status-error';
            case GraphSessionStatus.ENDED:
                return 'status-completed';
            case GraphSessionStatus.WAITING_FOR_USER:
                return 'status-waiting';
            case GraphSessionStatus.PENDING:
                return 'status-pending';
            case GraphSessionStatus.EXPIRED:
                return 'status-expired';
            case GraphSessionStatus.STOP:
                return 'status-stop';
            default:
                return 'status-unknown';
        }
    }

    get statusIcon(): string {
        switch (this.status) {
            case GraphSessionStatus.RUNNING:
                return 'ti ti-player-play';
            case GraphSessionStatus.ERROR:
                return 'ti ti-alert-triangle';
            case GraphSessionStatus.ENDED:
                return 'ti ti-check';
            case GraphSessionStatus.WAITING_FOR_USER:
                return 'ti ti-hourglass';
            case GraphSessionStatus.PENDING:
                return 'ti ti-clock';
            case GraphSessionStatus.EXPIRED:
                return 'ti ti-clock-pause';
            case GraphSessionStatus.STOP:
                return 'ti ti-player-stop';
            default:
                return 'ti ti-question-mark';
        }
    }
}
