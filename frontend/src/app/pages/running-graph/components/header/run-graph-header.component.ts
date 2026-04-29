import { Dialog } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { Component, HostListener, Input } from '@angular/core';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { Router, RouterModule } from '@angular/router';

import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import { GraphDto } from '../../../../features/flows/models/graph.model';
import { GraphSessionStatus } from '../../../../features/flows/services/flows-sessions.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { StatusBadgeComponent } from '../../../../shared/components/status-badge/status-badge.component';
import { RunGraphPageService } from '../../services/run-graph-page.service';
import { MemoriesSidebarComponent } from '../memory-sidebar/components/memory-sidebar/memory-sidebar.component';
import { MemoryService } from '../memory-sidebar/service/memory.service';
import { SessionFilesButtonComponent } from './session-files-button/session-files-button.component';

@Component({
    selector: 'app-running-graph-header',
    standalone: true,
    imports: [
        CommonModule,
        RouterModule,
        MatButtonModule,
        MatBadgeModule,
        AppSvgIconComponent,
        StatusBadgeComponent,
        MemoriesSidebarComponent,
        SessionFilesButtonComponent,
    ],
    template: `
        <div class="header">
            <div class="breadcrumbs">
                <div
                    class="flows-prefix"
                    routerLink="/flows"
                >
                    <app-svg-icon
                        icon="arrow-left"
                        size="20px"
                        class="back-arrow"
                    />
                    <span>Flows</span>
                </div>
                <span class="slash">/</span>
                <span
                    class="flow-name project-link"
                    (click)="onFlowClick()"
                    >{{ graphName || '...' }}</span
                >
                <span class="slash">/</span>
                <app-status-badge [sessionStatus]="sessionStatus"></app-status-badge>
            </div>
            <div class="view-options"></div>
            <div class="actions">
                @if (sessionId) {
                    <app-session-files-button
                        [sessionId]="sessionId"
                        [sessionStatus]="sessionStatus"
                    ></app-session-files-button>
                }
                <button
                    mat-button
                    class="sessions-button"
                    (click)="openSessionsDialog()"
                    [disabled]="!graphData"
                >
                    <span class="btn-label">Sessions</span>
                </button>
                <button
                    mat-button
                    class="memories-button"
                    (click)="toggleMemoriesSidebar()"
                >
                    <span class="btn-label">Memories</span>
                    <span
                        class="memories-badge"
                        matBadge="{{ memoriesCount }}"
                        matBadgeColor="accent"
                        *ngIf="memoriesCount > 0"
                    ></span>
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
                gap: 12px;
                height: 5rem !important;
                width: 100%;
                min-width: 0;
                overflow: visible;
                padding: 0 clamp(1rem, 4vw, 3rem);
                border-bottom: 1px solid var(--color-divider-subtle);

                position: relative;
                z-index: 10;

                .breadcrumbs {
                    display: flex;
                    align-items: center;
                    flex: 1 1 auto;
                    min-width: 0;
                    overflow: hidden;
                    white-space: nowrap;

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
                        flex-shrink: 0;

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
                        flex-shrink: 0;
                    }

                    .flow-name {
                        color: var(--white);
                        min-width: 0;
                        flex: 0 1 auto;
                        overflow: hidden;
                        text-overflow: ellipsis;
                        white-space: nowrap;
                        display: block;
                        vertical-align: bottom;
                        &:hover {
                            text-decoration: underline;
                        }
                    }

                    app-status-badge {
                        flex-shrink: 0;
                    }
                }

                .actions {
                    display: flex;
                    align-items: center;
                    gap: 16px;
                    min-width: 0;
                    margin-left: auto;
                    flex: 0 1 auto;
                    max-width: 100%;
                    overflow: visible;
                }

                app-session-files-button {
                    min-width: 0;
                    max-width: 100%;
                    flex: 0 1 auto;
                }

                .sessions-button,
                .memories-button {
                    display: flex;
                    align-items: center;
                    justify-content: flex-start;
                    gap: 8px;
                    color: var(--gray-400) !important;
                    background: transparent !important;
                    border: none !important;
                    border-radius: 6px !important;
                    padding: 8px 12px !important;
                    min-width: 0 !important;
                    max-width: 100%;
                    flex: 0 1 auto;
                    line-height: 1 !important;
                    overflow: hidden;

                    .btn-label {
                        display: block;
                        flex: 1 1 auto;
                        min-width: 0;
                        overflow: hidden;
                        white-space: nowrap;
                        text-overflow: ellipsis;
                    }

                    &:hover {
                        color: var(--white) !important;
                        background: rgba(255, 255, 255, 0.05) !important;
                    }

                    &:disabled {
                        opacity: 0.5 !important;
                        cursor: not-allowed !important;

                        &:hover {
                            color: var(--gray-400) !important;
                            background: transparent !important;
                        }
                    }

                    mat-icon {
                        font-size: 18px;
                        width: 18px;
                        height: 18px;
                        margin-top: 2px;
                    }

                    span {
                        font-size: 14px;
                        font-weight: 400;
                    }
                }

                .memories-button {
                    position: relative;

                    .memories-badge {
                        flex-shrink: 0;
                    }
                }
            }

            @media (max-width: 1100px) {
                .header {
                    .actions {
                        gap: 8px;
                    }

                    .sessions-button,
                    .memories-button {
                        padding: 8px 10px !important;
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
