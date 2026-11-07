import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { AppSvgIconComponent, CopyButtonComponent } from '@shared/components';

import { GraphMessage, MessageType } from '../../../../models/graph-session-message.model';
import { RuntimeNodeLabelPipe } from '../../../../pipes/runtime-node-label.pipe';

@Component({
    selector: 'app-error-message',
    imports: [CommonModule, AppSvgIconComponent, CopyButtonComponent, RuntimeNodeLabelPipe],
    template: `
        <div class="session-message error-container">
            <div
                class="error-header"
                (click)="toggleMessage()"
            >
                <div class="play-arrow">
                    <app-svg-icon
                        [icon]="isMessageExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                        size="1rem"
                    />
                </div>
                <div class="icon-container">
                    <app-svg-icon
                        icon="alert-circle"
                        size="1rem"
                    />
                </div>
                <h3>
                    <button
                        type="button"
                        class="message-toggle"
                        [attr.aria-expanded]="isMessageExpanded"
                    >
                        @if (message.name) {
                            <span class="node-name">{{ message.name | runtimeNodeLabel }}</span> failed
                        } @else {
                            Error
                        }
                    </button>
                </h3>
            </div>

            <!-- Collapsible Content -->
            <div
                class="collapsible-content grid-collapsible"
                [class.expanded]="isMessageExpanded"
                [inert]="!isMessageExpanded"
            >
                <div class="error-content">
                    <!-- Error Details Section -->
                    <div class="error-section">
                        <button
                            type="button"
                            class="section-heading"
                            [attr.aria-expanded]="isErrorExpanded"
                            (click)="toggleErrorSection($event)"
                        >
                            <app-svg-icon
                                [icon]="isErrorExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                                size="1rem"
                            />
                            Error Details
                        </button>
                        <div
                            class="collapsible-content grid-collapsible"
                            [class.expanded]="isErrorExpanded"
                            [inert]="!isErrorExpanded"
                        >
                            <div class="grid-collapsible__inner">
                                <div
                                    class="result-content"
                                    [ngClass]="{ collapsed: isCollapsed && shouldShowToggle() }"
                                >
                                    <app-copy-button [text]="getFormattedErrorDetails()" />
                                    <pre>{{ getFormattedErrorDetails() }}</pre>
                                </div>
                                @if (shouldShowToggle() && isErrorExpanded) {
                                    <button
                                        type="button"
                                        class="toggle-button"
                                        (click)="toggleCollapse($event)"
                                    >
                                        {{ isCollapsed ? 'Show more' : 'Show less' }}
                                    </button>
                                }
                            </div>
                        </div>
                    </div>

                    <!-- Optional Data Subsection -->
                    @if (hasErrorData()) {
                        <div class="error-data-container">
                            <button
                                type="button"
                                class="section-heading"
                                [attr.aria-expanded]="isDataExpanded"
                                (click)="toggleDataSection($event)"
                            >
                                <app-svg-icon
                                    [icon]="isDataExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                                    size="1rem"
                                />
                                Data
                            </button>
                            <div
                                class="collapsible-content grid-collapsible"
                                [class.expanded]="isDataExpanded"
                                [inert]="!isDataExpanded"
                            >
                                <div class="collapsible-inner">
                                    <div class="result-content">
                                        <pre>{{ getFormattedErrorData() }}</pre>
                                    </div>
                                </div>
                            </div>
                        </div>
                    }
                </div>
            </div>
        </div>
    `,
    changeDetection: ChangeDetectionStrategy.Eager,
    styles: [
        `
            // The title is the button that folds the message; drawn as the plain title it was. The header row keeps
            // its own click, which this button's click reaches.
            .message-toggle {
                padding: 0;
                border: none;
                background: none;
                color: inherit;
                font: inherit;
                text-align: left;
                cursor: inherit;
            }

            .error-container {
                position: relative;
                background-color: var(--color-nodes-background);
                border-radius: 8px;
                padding: var(--message-padding, 0.5rem 1rem);
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
                margin-right: 8px;
                display: flex;
                align-items: center;

                app-svg-icon {
                    color: #ff6b6b;
                }
            }

            .icon-container {
                width: 28px;
                height: 28px;
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
                font-size: var(--text-body-medium-size);
                font-weight: var(--text-body-medium-weight);
                line-height: var(--text-body-medium-line-height);
                margin: 0;
                /* A node name with no spaces would otherwise run past the card's edge. */
                min-width: 0;
                overflow-wrap: anywhere;
            }

            .node-name {
                color: var(--red-400);
                font-weight: var(--text-body-weight);
            }

            /* Collapsible content container */
            .collapsible-content {
                overflow: hidden;
                position: relative;
            }

            .error-content {
                display: flex;
                flex-direction: column;
                gap: 1rem;
                padding-left: 4.5rem;
            }

            .error-content > :first-child {
                margin-top: 1.25rem;
            }

            /* Section styling */
            // The button that folds its section, drawn as the heading row it was.
            .section-heading {
                width: 100%;
                padding: 0;
                border: none;
                background: none;
                font-family: inherit;
                text-align: left;
                font-size: var(--text-body-medium-size);
                font-weight: var(--text-body-medium-weight);
                line-height: var(--text-body-medium-line-height);
                color: var(--gray-300);
                margin-bottom: 0.5rem;
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;

                // Drawn inside: the collapsible content around clips it.
                &:focus-visible {
                    outline-offset: -2px;
                }

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
                position: relative;
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

                &:hover app-copy-button {
                    opacity: 1;
                }
            }

            .toggle-button {
                background-color: transparent;
                border: none;
                color: #ff6b6b;
                font-size: 0.875rem;
                cursor: pointer;
                padding: 0.5rem;
                text-align: center;
                width: 100%;
                margin-top: 0.25rem;
            }

            .toggle-button:is(:hover, :focus-visible) {
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
            this.message.message_data.message_type === MessageType.ERROR &&
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
            this.message.message_data.message_type === MessageType.ERROR &&
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
