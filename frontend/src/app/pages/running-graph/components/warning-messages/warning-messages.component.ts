import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { expandCollapseAnimation } from '../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-warning-messages',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    animations: [expandCollapseAnimation],
    template: `
        <div
            class="warning-container"
            *ngIf="messages && messages.length > 0"
        >
            <div
                class="warning-header"
                (click)="toggleExpand()"
            >
                <div class="play-arrow">
                    <app-svg-icon
                        [icon]="isExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                        size="1rem"
                    />
                </div>
                <div class="icon-container">
                    <app-svg-icon
                        icon="alert-triangle"
                        size="1rem"
                    />
                </div>
                <h3>Warnings</h3>
                <span class="warning-count">({{ messages.length }})</span>
            </div>

            <div
                class="collapsible-content"
                [@expandCollapse]="isExpanded ? 'expanded' : 'collapsed'"
            >
                <div class="warning-content">
                    @for (message of messages; track message; let i = $index) {
                        <div class="warning-item">
                            <span class="warning-bullet">{{ i + 1 }}.</span>
                            <p class="warning-text">{{ message }}</p>
                        </div>
                    }
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            .warning-container {
                background-color: var(--color-nodes-background);
                border-radius: 8px;
                padding: var(--space-lg) var(--space-xl);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border-left: 4px solid #f56a00;
                margin-bottom: var(--space-lg);
            }

            .warning-header {
                display: flex;
                align-items: center;
                gap: var(--space-md);
                cursor: pointer;
                user-select: none;
            }

            .play-arrow {
                display: flex;
                align-items: center;

                i {
                    color: #f56a00;
                    font-size: var(--font-size-xl);
                    transition: transform 0.3s ease;
                }
            }

            .warning-count {
                color: var(--gray-400);
                font-size: var(--font-size-md);
                font-weight: var(--font-weight-medium);
            }

            .collapsible-content {
                overflow: hidden;
            }

            .icon-container {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                background-color: #f56a00;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;

                i {
                    color: var(--gray-900);
                    font-size: var(--font-size-xl);
                }
            }

            h3 {
                color: var(--gray-100);
                font-size: var(--font-size-lg);
                font-weight: var(--font-weight-semibold);
                margin: 0;
            }

            .warning-content {
                display: flex;
                flex-direction: column;
                gap: var(--space-sm);
                padding-left: 56px;
                margin-top: var(--space-md);
            }

            .warning-item {
                display: flex;
                gap: var(--space-sm);
                align-items: flex-start;
            }

            .warning-bullet {
                color: #f56a00;
                font-weight: var(--font-weight-semibold);
                font-size: var(--font-size-md);
                flex-shrink: 0;
            }

            .warning-text {
                color: var(--gray-300);
                font-size: var(--font-size-md);
                line-height: 1.5;
                margin: 0;
            }
        `,
    ],
})
export class WarningMessagesComponent {
    @Input() messages: string[] | null = null;

    isExpanded = true;

    toggleExpand(): void {
        this.isExpanded = !this.isExpanded;
    }
}
