import { Component, Input, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { Dialog } from '@angular/cdk/dialog';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { StatusBadgeComponent } from '../../../../shared/components/status-badge/status-badge.component';
import { GraphSessionStatus } from '../../../../features/flows/services/flows-sessions.service';
import { RunGraphPageService } from '../../run-graph-page.service';
import { MemoriesSidebarComponent } from '../memory-sidebar/components/memory-sidebar/memory-sidebar.component';
import { MemoryService } from '../memory-sidebar/service/memory.service';
import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import { GraphDto } from '../../../../features/flows/models/graph.model';

@Component({
  selector: 'app-running-graph-header',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    AppIconComponent,
    StatusBadgeComponent,
    MemoriesSidebarComponent,
  ],
  template: `
    <div class="header">
      <div class="breadcrumbs">
        <div class="flows-prefix" routerLink="/flows">
          <app-icon [icon]="'ui/arrow-left'" size="20" class="back-arrow" />
          <span>Flows</span>
        </div>
        <span class="slash">/</span>
        <span class="flow-name project-link" (click)="onFlowClick()">{{
          graphName || '...'
        }}</span>
        <span class="slash">/</span>
        <app-status-badge [sessionStatus]="sessionStatus"></app-status-badge>
      </div>
      <div class="view-options"></div>
      <div class="actions">
        <button
          class="custom-button sessions-button"
          (click)="openSessionsDialog()"
          [disabled]="!graphData"
        >
          <i class="ti ti-history"></i>
          <span>Sessions</span>
        </button>
        <button
          class="custom-button memories-button"
          (click)="toggleMemoriesSidebar()"
        >
          <i class="ti ti-brain"></i>
          <span>Memories</span>
          <div class="badge" *ngIf="memoriesCount > 0">
            {{ memoriesCount }}
          </div>
        </button>
      </div>
    </div>

    <!-- Memories Sidebar Component -->
    <app-memories-sidebar
      [isOpen]="showMemoriesSidebar"
      [memories]="memories"
      (close)="closeSidebar()"
      (deleteMemoryEvent)="handleDeleteMemory($event)"
    ></app-memories-sidebar>
  `,
  styles: [
    `
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        height: 5rem !important;
        width: 100%;
        padding: 0 3rem;
        border-bottom: 1px solid var(--color-divider-subtle);

        position: relative;
        z-index: 10;

        .breadcrumbs {
          display: flex;
          align-items: center;

          .flows-prefix,
          .flow-name,
          .slash {
            font-size: 24px;
            font-weight: 400;
            letter-spacing: -0.02em;
            line-height: 1;
            margin: 0;
            padding: 0;
          }

          .flows-prefix {
            color: rgba(255, 255, 255, 0.6);
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            position: relative;

            .back-arrow {
              margin-top: 3px;
              opacity: 1;
              transform: translateX(0);
              transition: all 0.3s ease;
            }

            span {
              line-height: 1;
            }

            &:hover {
              color: rgba(255, 255, 255, 0.9);
            }
          }

          .slash {
            color: var(--gray-500);
            margin: 0 0.5rem;
          }

          .flow-name {
            color: var(--white);
            &:hover {
              text-decoration: underline;
            }
          }
        }

        .actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .custom-button {
          border: none;
          border-radius: 6px;
          padding: 8px 12px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;

          &:hover {
            background: rgba(255, 255, 255, 0.05);
          }
        }

        .sessions-button,
        .memories-button {
          display: flex;
          align-items: center;
          gap: 8px;
          color: var(--gray-400);
          position: relative;

          &:hover {
            color: var(--white);
          }

          &:disabled {
            opacity: 0.5;
            cursor: not-allowed;

            &:hover {
              color: var(--gray-400);
            }
          }

          i {
            margin-top: 2px;
            font-size: 18px;
            width: 18px;
            height: 18px;
          }
        }

        .memories-button {
          .badge {
            background-color: var(--accent-color);
            color: var(--white);
            font-size: 12px;
            font-weight: 500;
            min-width: 20px;
            height: 20px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-left: 4px;
          }
        }
      }
    `,
  ],
})
export class RunningGraphHeaderComponent {
  @Input() graphId: number | null = null;
  @Input() sessionId: string | null | undefined = null;
  @Input() graphName: string | null | undefined = null;
  @Input() sessionStatus: GraphSessionStatus | null = null;
  @Input() graphData: GraphDto | null = null;

  public showMemoriesSidebar = false;

  constructor(
    private runGraphPageService: RunGraphPageService,
    private memoryService: MemoryService,
    private dialog: Dialog,
    private router: Router
  ) {}

  @HostListener('document:keydown.escape')
  handleEscapeKey() {
    this.closeSidebar();
  }

  get memories() {
    return this.runGraphPageService.getMemories();
  }

  get memoriesCount(): number {
    return this.memories.length;
  }

  toggleMemoriesSidebar(): void {
    this.showMemoriesSidebar = !this.showMemoriesSidebar;
  }

  closeSidebar(): void {
    this.showMemoriesSidebar = false;
  }

  onFlowClick() {
    if (this.graphId) {
      this.router.navigate(['flows', this.graphId]);
    }
  }
  openSessionsDialog(): void {
    if (this.graphData) {
      this.dialog.open(FlowSessionsListComponent, {
        data: { flow: this.graphData },
        panelClass: 'custom-dialog-panel',
      });
    }
  }

  handleDeleteMemory(memoryId: string): void {
    this.memoryService.deleteMemory(memoryId).subscribe({
      next: () => {
        // On successful deletion, update local state
        this.runGraphPageService.deleteMemory(memoryId);
      },
      error: (error) => {
        console.error('Error deleting memory:', error);
        // Could add error handling or notification here
      },
    });
  }
}
