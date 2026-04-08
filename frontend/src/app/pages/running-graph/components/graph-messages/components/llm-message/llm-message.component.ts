import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { MarkdownModule } from 'ngx-markdown';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GraphMessage, LLMMessageData } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-llm-message',
    standalone: true,
    imports: [CommonModule, MarkdownModule, AppSvgIconComponent],
    animations: [expandCollapseAnimation],
    template: `
        <div class="llm-flow-container">
            <!-- LLM Message Header with Toggle -->
            <div class="llm-header" (click)="toggleMessage()">
                <div class="play-arrow">
                    <app-svg-icon [icon]="isMessageExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1.1rem" />
                </div>
                <div class="icon-container">
                    <app-svg-icon icon="message-circle" size="1.25rem" />
                </div>
                <h3>LLM Response</h3>
            </div>

            <!-- Collapsible LLM Content -->
            <div class="collapsible-content" [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'">
                <div class="llm-content">
                    <!-- Response Subsection -->
                    <div class="llm-section">
                        <div class="section-heading" (click)="toggleResponseSection()">
                            <app-svg-icon [icon]="isResponseExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1.1rem" />
                            Response
                        </div>
                        <div
                            class="collapsible-content"
                            [@expandCollapse]="isResponseExpanded ? 'expanded' : 'collapsed'"
                        >
                            <div class="result-content" [ngClass]="{ collapsed: isCollapsed && shouldShowToggle() }">
                                <markdown [data]="llmResponse"></markdown>
                            </div>
                            <button
                                *ngIf="shouldShowToggle() && isResponseExpanded"
                                class="toggle-button"
                                (click)="toggleCollapse()"
                            >
                                {{ isCollapsed ? 'Show more' : 'Show less' }}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            .llm-flow-container {
                background-color: var(--color-nodes-background);
                border-radius: 8px;
                padding: 1.25rem;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border-left: 4px solid #36cfc9; /* Teal accent */
            }

            .llm-header {
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
                    color: #36cfc9;
                }
            }

            .icon-container {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background-color: #36cfc9;
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

            .llm-content {
                display: flex;
                flex-direction: column;
                padding-left: 5.5rem;
                margin-top: 1.25rem;
                overflow: hidden;
            }

            .llm-section {
                width: 100%;
            }

            .section-heading {
                font-weight: 500;
                color: var(--gray-300);
                margin-bottom: 0.5rem;
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;
            }

            .section-heading app-svg-icon {
                margin-right: 8px;
                color: #36cfc9;
                margin-left: -3px;
            }

            .collapsible-content {
                overflow: hidden;
                position: relative;
            }

            .collapsible-content.ng-animating {
                overflow: hidden;
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
            }

            .result-content.collapsed {
                max-height: 200px;
            }

            .toggle-button {
                background-color: transparent;
                border: none;
                color: #36cfc9;
                font-size: 0.85rem;
                cursor: pointer;
                padding: 0.5rem;
                text-align: center;
                width: 100%;
                margin-top: 0.25rem;
                margin-left: 23px;
            }

            .toggle-button:hover {
                text-decoration: underline;
            }
        `,
    ],
})
export class LlmMessageComponent {
    @Input() message!: GraphMessage;

    isMessageExpanded = false;
    isResponseExpanded = true;
    isCollapsed = true;

    get llmResponse(): string {
        if (this.message.message_data && this.message.message_data.message_type === 'llm') {
            const data = this.message.message_data as LLMMessageData;
            return data.response;
        }
        return '';
    }

    toggleMessage(): void {
        this.isMessageExpanded = !this.isMessageExpanded;
    }

    toggleResponseSection(): void {
        this.isResponseExpanded = !this.isResponseExpanded;
    }

    toggleCollapse(): void {
        this.isCollapsed = !this.isCollapsed;
    }

    shouldShowToggle(): boolean {
        const response = this.llmResponse;
        // Show the toggle button if content is longer than ~5 lines or 500 chars
        return response.split('\n').length > 5 || response.length > 500;
    }
}
