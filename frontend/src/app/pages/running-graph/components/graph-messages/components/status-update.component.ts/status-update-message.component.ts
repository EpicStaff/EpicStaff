import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GraphMessage, UpdateSessionStatusMessageData } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-status-update-message',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    template: `
        <div class="status-update-message">
            <div class="status-info">
                <span class="project-name">{{ projectName }}</span>
                <span class="status-value">Status: {{ status }}</span>
            </div>
            <div
                class="status-data"
                *ngIf="hasStatusData()"
            >
                <div class="status-data-label">
                    <app-svg-icon
                        icon="info-circle"
                        size="1rem"
                    />
                    Status Data:
                </div>
                <pre class="status-data-content">{{ statusData | json }}</pre>
            </div>
        </div>
    `,
    styles: [
        `
            .status-update-message {
                padding: 1rem;
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                background-color: var(--gray-900);

                .status-info {
                    display: flex;
                    gap: 1rem;
                    flex-wrap: wrap;
                    margin-bottom: 0.75rem;
                    .project-name {
                        color: var(--gray-500);
                    }
                    .status-value {
                        color: var(--gray-100);
                        font-weight: 500;
                    }
                }

                .status-data {
                    .status-data-label {
                        display: flex;
                        align-items: center;
                        font-weight: 500;
                        margin-bottom: 0.25rem;
                        color: var(--gray-400);
                        app-svg-icon {
                            margin-right: 0.5rem;
                        }
                    }
                    .status-data-content {
                        background-color: var(--gray-800);
                        border-radius: 6px;
                        padding: 0.75rem;
                        font-family: 'Courier New', monospace;
                        font-size: 0.8rem;
                        overflow-x: auto;
                        color: var(--gray-200);
                    }
                }
            }
        `,
    ],
})
export class StatusUpdateMessageComponent {
    @Input() message!: GraphMessage;

    get updateStatusData(): UpdateSessionStatusMessageData | null {
        if (this.message.message_data && this.message.message_data.message_type === 'update_session_status') {
            return this.message.message_data as UpdateSessionStatusMessageData;
        }
        return null;
    }

    get status(): string {
        return this.updateStatusData ? this.updateStatusData.status : '';
    }

    get statusData(): Record<string, unknown> {
        return this.updateStatusData ? this.updateStatusData.status_data : {};
    }

    get projectName(): string {
        return this.updateStatusData ? `Project #${this.updateStatusData.crew_id}` : '';
    }

    hasStatusData(): boolean {
        return !!(this.statusData && Object.keys(this.statusData).length);
    }
}
