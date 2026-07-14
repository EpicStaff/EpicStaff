import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import { GraphMessage, UpdateSessionStatusMessageData } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-status-update-message',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, CopyButtonComponent],
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
                <div class="status-data-wrapper">
                    <app-copy-button [text]="statusDataJson" />
                    <pre class="status-data-content">{{ statusData | json }}</pre>
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            .status-update-message {
                padding: var(--space-lg);
                border: 1px solid var(--gray-750);
                border-radius: var(--radius-lg);
                background-color: var(--gray-900);

                .status-info {
                    display: flex;
                    gap: var(--space-lg);
                    flex-wrap: wrap;
                    margin-bottom: var(--space-md);
                    .project-name {
                        color: var(--gray-500);
                    }
                    .status-value {
                        color: var(--gray-100);
                        font-weight: var(--font-weight-medium);
                    }
                }

                .status-data {
                    .status-data-label {
                        display: flex;
                        align-items: center;
                        font-weight: var(--font-weight-medium);
                        margin-bottom: var(--space-2xs);
                        color: var(--gray-400);
                        app-svg-icon {
                            margin-right: var(--space-sm);
                        }
                    }
                    .status-data-wrapper {
                        position: relative;

                        &:hover app-copy-button {
                            opacity: 1;
                        }
                    }

                    .status-data-content {
                        background-color: var(--gray-800);
                        border-radius: var(--radius-md);
                        padding: var(--space-md);
                        font-family: 'Courier New', monospace;
                        font-size: var(--font-size-sm);
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

    get statusDataJson(): string {
        return JSON.stringify(this.statusData, null, 2);
    }
}
