import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { CollapseOnOverflowDirective } from '../../../shared/directives/collapse-on-overflow.directive';
import { GraphSessionStatus } from '../../models';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-status-badge',
    imports: [NgClass, AppSvgIconComponent, CollapseOnOverflowDirective],
    template: `
        <span
            class="status-badge"
            [ngClass]="statusClass"
            [appCollapseOnOverflow]="true"
            collapseOnOverflowTarget=".status-text"
            collapseOnOverflowClass="status-badge--icon-only"
            collapseOnOverflowRequireSelector="app-svg-icon"
        >
            @if (sessionStatus === GraphSessionStatus.STOP) {
                <span
                    class="status-stop-square"
                    aria-hidden="true"
                ></span>
            } @else if (statusIcon) {
                <app-svg-icon
                    [icon]="statusIcon"
                    size="14px"
                    aria-hidden="true"
                />
            }
            <span class="status-text">{{ statusText }}</span>
        </span>
    `,
    changeDetection: ChangeDetectionStrategy.Eager,
    styles: [
        `
            .status-badge {
                margin-left: 0.5rem;
                margin-top: 0.4rem;
                display: inline-flex;
                align-items: center;
                padding: 0.25rem 0.75rem;
                border-radius: 12px;
                font-size: 0.8rem;
                font-weight: 500;
                gap: 6px;
                flex-shrink: 0;

                &.status-badge--icon-only {
                    padding: 0.25rem 0.5rem;

                    .status-text {
                        display: none;
                    }
                }
            }

            .status-running {
                background-color: rgba(41, 121, 255, 0.15);
                color: #5e9eff;
                animation: pulse 1.5s infinite ease-in-out;
            }

            .status-error {
                background-color: rgba(16, 2, 2, 0.15);
                color: #c69999ff;
            }

            .status-badge.status-stop {
                height: 28px;
                padding: 4px 8px 4px 4px;
                border-radius: var(--radius-sm);
                gap: 4px;
                background-color: var(--red-alpha-8-flat);
                color: var(--red-500);
                font-family: Inter, sans-serif;
                font-size: 12px;
                font-weight: 400;
                line-height: 1.3;
                letter-spacing: 0;
            }

            .status-stop-square {
                flex-shrink: 0;
                width: 10px;
                height: 10px;
                margin: 5px;
                border-radius: 1px;
                background-color: var(--red-500);
            }

            .status-waiting {
                background-color: rgba(255, 170, 0, 0.15);
                color: #ffc14d;
            }

            .status-complete {
                background-color: rgba(80, 205, 137, 0.15);
                color: #6bdb9a;
            }

            .status-pending {
                background-color: rgba(150, 150, 150, 0.15);
                color: #9898a9;
            }

            @keyframes pulse {
                0% {
                    opacity: 1;
                }
                50% {
                    opacity: 0.7;
                }
                100% {
                    opacity: 1;
                }
            }
        `,
    ],
})
export class StatusBadgeComponent {
    @Input() sessionStatus: GraphSessionStatus | null = null;

    protected readonly GraphSessionStatus = GraphSessionStatus;

    get statusText(): string {
        if (!this.sessionStatus) return '';

        switch (this.sessionStatus) {
            case GraphSessionStatus.RUNNING:
                return 'Running';
            case GraphSessionStatus.ERROR:
                return 'Error';
            case GraphSessionStatus.ENDED:
                return 'Completed';
            case GraphSessionStatus.WAITING_FOR_USER:
                return 'Waiting for User';
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
        if (!this.sessionStatus) return '';

        switch (this.sessionStatus) {
            case GraphSessionStatus.RUNNING:
                return 'status-running';
            case GraphSessionStatus.ERROR:
                return 'status-error';
            case GraphSessionStatus.ENDED:
                return 'status-complete';
            case GraphSessionStatus.WAITING_FOR_USER:
                return 'status-waiting';
            case GraphSessionStatus.PENDING:
                return 'status-pending';
            case GraphSessionStatus.EXPIRED:
                return 'status-expired';
            case GraphSessionStatus.STOP:
                return 'status-stop';
            default:
                return '';
        }
    }

    get statusIcon(): string {
        if (!this.sessionStatus) return '';

        switch (this.sessionStatus) {
            case GraphSessionStatus.RUNNING:
                return 'play';
            case GraphSessionStatus.ERROR:
                return 'warning';
            case GraphSessionStatus.ENDED:
                return 'check';
            case GraphSessionStatus.WAITING_FOR_USER:
                return 'hourglass';
            case GraphSessionStatus.PENDING:
                return 'status-pending';
            case GraphSessionStatus.EXPIRED:
                return '';
            case GraphSessionStatus.STOP:
                return '';
            default:
                return '';
        }
    }
}
