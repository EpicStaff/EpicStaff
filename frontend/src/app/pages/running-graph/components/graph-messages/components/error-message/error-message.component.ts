import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GraphMessage } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-error-message',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    animations: [expandCollapseAnimation],
    template: `
        <div class="error-container">
            <div class="error-header" (click)="toggleMessage()">
                <div class="play-arrow">
                    <app-svg-icon [icon]="isMessageExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1rem" />
                </div>
                <div class="icon-container">
                    <app-svg-icon icon="alert-circle" size="1rem" />
                </div>
                <h3>Error</h3>
            </div>

            <!-- Collapsible Content -->
            <div class="collapsible-content" [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'">
                <div class="error-content">
                    <!-- Error Details Section -->
                    <div class="error-section">
                        <div class="section-heading" (click)="toggleErrorSection($event)">
                            <app-svg-icon [icon]="isErrorExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1rem" />
                            Error Details
                        </div>
                        <div class="collapsible-content" [@expandCollapse]="isErrorExpanded ? 'expanded' : 'collapsed'">
                            <div class="result-content" [ngClass]="{ collapsed: isCollapsed && shouldShowToggle() }">
                                <pre>{{ getFormattedErrorDetails() }}</pre>
                            </div>
                            <button
                                *ngIf="shouldShowToggle() && isErrorExpanded"
                                class="toggle-button"
                                (click)="toggleCollapse($event)"
                            >
                                {{ isCollapsed ? 'Show more' : 'Show less' }}
                            </button>
                        </div>
                    </div>

                    <!-- Optional Data Subsection -->
                    <div class="error-data-container" *ngIf="hasErrorData()">
                        <div class="section-heading" (click)="toggleDataSection($event)">
                            <app-svg-icon [icon]="isDataExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1rem" />
                            Data
                        </div>
                        <div class="collapsible-content" [@expandCollapse]="isDataExpanded ? 'expanded' : 'collapsed'">
                            <div class="result-content">
                                <pre>{{ getFormattedErrorData() }}</pre>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            .error-container {
                position: relative;
                background-color: var(--color-nodes-background);
                border-radius: 8px;
                padding: 1.25rem;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border-left: 4px solid #ff6b6b;
            }

            .error-header {
                display: flex;
                align-items: center;
                cursor: pointer;
                user-select: none;
            }

            .play-arrow {
                margin-right: 16px;
                display: flex;
                align-items: center;

                app-svg-icon {
                    color: #ff6b6b;
                }
            }

            .icon-container {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background-color: #ff6b6b;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 20px;
                flex-shrink: 0;

                app-svg-icon {
                    color: var(--gray-900);
                }
            }

            h3 {
                color: var(--gray-100);
                font-size: 1.1rem;
                font-weight: 600;
                margin: 0;
            }

            /* Collapsible content container */
            .collapsible-content {
                overflow: hidden;
                position: relative;

                &.ng-animating {
                    overflow: hidden;
                }
            }

            .error-content {
                display: flex;
                flex-direction: column;
                gap: 1rem;
                padding-left: 5.5rem;
                margin-top: 1.25rem;
            }

            /* Section styling */
            .section-heading {
                font-weight: 500;
                color: var(--gray-300);
                margin-bottom: 0.5rem;
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;

                app-svg-icon {
                    margin-right: 8px;
                    color: #ff6b6b;
                    margin-left: -3px;
                }
            }

            .error-section,
            .error-data-container {
            }

            .result-content {
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                padding: 1rem;
                color: var(--gray-200);
                white-space: pre-wrap;
                word-break: break-word;
                overflow-y: auto;
                transition: max-height 0.3s ease;
                margin-left: 23px;
                padding-inline: 10px;

                &.collapsed {
                    max-height: 200px;
                }
            }

            .toggle-button {
                background-color: transparent;
                border: none;
                color: #ff6b6b;
                font-size: 0.85rem;
                cursor: pointer;
                padding: 0.5rem;
                text-align: center;
                width: 100%;
                margin-top: 0.25rem;
            }

            .toggle-button:hover {
                text-decoration: underline;
            }

            pre {
                margin: 0;
                white-space: pre-wrap;
                font-family: 'Courier New', monospace;
            }
        `,
    ],
})
export class ErrorMessageComponent {
    @Input() message!: GraphMessage;

    // Main message expand/collapse
    isMessageExpanded = true;

    // Section expand/collapse controls
    isErrorExpanded = true;
    isCollapsed = true;
    isDataExpanded = false;

    toggleMessage(): void {
        this.isMessageExpanded = !this.isMessageExpanded;
    }

    toggleErrorSection(event: Event): void {
        // Stop the click event from propagating to parent elements
        event.stopPropagation();
        this.isErrorExpanded = !this.isErrorExpanded;
    }

    toggleCollapse(event: Event): void {
        // Stop the click event from propagating to parent elements
        event.stopPropagation();
        this.isCollapsed = !this.isCollapsed;
    }

    shouldShowToggle(): boolean {
        const details = this.getFormattedErrorDetails();
        // Show "Show more/Show less" if content is longer than ~5 lines or 500 chars
        return details.split('\n').length > 5 || details.length > 500;
    }

    toggleDataSection(event: Event): void {
        // Stop the click event from propagating to parent elements
        event.stopPropagation();
        this.isDataExpanded = !this.isDataExpanded;
    }

    // ---------- Primary Error Details ----------
    get errorDetails(): string | Record<string, unknown> {
        if (
            this.message.message_data &&
            this.message.message_data.message_type === 'error' &&
            'details' in this.message.message_data
        ) {
            return this.message.message_data.details;
        }
        return { error: 'Unknown error' };
    }

    getFormattedErrorDetails(): string {
        const details = this.errorDetails;
        if (typeof details === 'string') {
            // Remove surrounding quotes if present
            if (details.startsWith('"') && details.endsWith('"')) {
                return details.substring(1, details.length - 1);
            }
            return details;
        }
        return JSON.stringify(details, null, 2);
    }

    // ---------- Additional Data Subsection ----------
    get errorData(): unknown {
        if (
            this.message.message_data &&
            this.message.message_data.message_type === 'error' &&
            'data' in this.message.message_data
        ) {
            return this.message.message_data.data;
        }
        return null;
    }

    hasErrorData(): boolean {
        return this.errorData !== null && this.errorData !== undefined;
    }

    getFormattedErrorData(): string {
        if (typeof this.errorData === 'string') {
            return this.errorData;
        } else if (this.errorData) {
            return JSON.stringify(this.errorData, null, 2);
        }
        return 'No additional data provided.';
    }
}
