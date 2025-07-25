import { Component, Input } from '@angular/core';
import { GraphSessionStatus } from '../../../features/flows/services/flows-sessions.service';
import { NgClass, NgIf } from '@angular/common';

@Component({
  selector: 'app-status-badge',
  standalone: true,
  imports: [NgClass, NgIf],
  template: `
    <span class="status-badge" [ngClass]="statusClass">
      <i
        *ngIf="sessionStatus !== GraphSessionStatus.EXPIRED"
        [ngClass]="statusIcon"
        aria-hidden="true"
      ></i>
      {{ statusText }}
    </span>
  `,
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

        i {
          font-size: 14px;
        }
      }
      .status-running {
        background-color: rgba(41, 121, 255, 0.15);
        color: #5e9eff;
        animation: pulse 1.5s infinite ease-in-out;
      }
      .status-error {
        background-color: rgba(255, 76, 76, 0.15);
        color: #ff7a7a;
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
        return 'status-pending';
      default:
        return '';
    }
  }

  get statusIcon(): string {
    if (!this.sessionStatus) return '';
    switch (this.sessionStatus) {
      case GraphSessionStatus.RUNNING:
        return 'ti ti-player-play';
      case GraphSessionStatus.ERROR:
        return 'ti ti-alert-triangle';
      case GraphSessionStatus.ENDED:
        return 'ti ti-check';
      case GraphSessionStatus.WAITING_FOR_USER:
        return 'ti ti-hourglass';
      case GraphSessionStatus.PENDING:
        return 'ti ti-circle-dot';
      case GraphSessionStatus.EXPIRED:
        return '';
      default:
        return '';
    }
  }
}
