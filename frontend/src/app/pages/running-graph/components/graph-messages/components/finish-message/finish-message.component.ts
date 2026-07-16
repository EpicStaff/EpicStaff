import { CommonModule } from '@angular/common';
import { Component, Input, OnInit } from '@angular/core';
import { NgxJsonViewerModule } from 'ngx-json-viewer';
import { MarkdownModule } from 'ngx-markdown';

import { GetProjectRequest } from '../../../../../../features/projects/models/project.model';
import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import { FinishMessageData, GraphMessage } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-finish-message',
    standalone: true,
    imports: [CommonModule, NgxJsonViewerModule, MarkdownModule, AppSvgIconComponent, CopyButtonComponent],
    animations: [expandCollapseAnimation],
    template: `
        <div class="finish-container">
            <!-- Finish Message Header with Toggle -->
            <div
                class="finish-header"
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
                        icon="flag-filled"
                        size="1rem"
                    />
                </div>
                <h3>
                    <span
                        class="project-name"
                        *ngIf="project && project.name"
                        >{{ project.name }}</span
                    >
                    <span *ngIf="!project || !project.name">Default Project</span>
                    finished
                </h3>
            </div>

            <!-- Collapsible Finish Content -->
            <div
                class="collapsible-content"
                [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
            >
                <div class="finish-content">
                    <!-- Variables Section -->
                    <div
                        class="variables-container"
                        *ngIf="hasVariables()"
                    >
                        <div
                            class="section-heading"
                            (click)="toggleSection('variables')"
                        >
                            <app-svg-icon
                                [icon]="isVariablesExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                                size="1rem"
                            />
                            Variables
                        </div>
                        <div
                            class="collapsible-content"
                            [@expandCollapse]="isVariablesExpanded ? 'expanded' : 'collapsed'"
                        >
                            <div class="variables-content">
                                <app-copy-button [text]="variablesJson" />
                                <ngx-json-viewer
                                    [json]="getVariables()"
                                    [expanded]="false"
                                ></ngx-json-viewer>
                            </div>
                        </div>
                    </div>

                    <!-- Final Output Section -->
                    <div class="output-container">
                        <div
                            class="section-heading"
                            (click)="toggleSection('output')"
                        >
                            <app-svg-icon
                                [icon]="isOutputExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                                size="1rem"
                            />
                            Final Output
                        </div>

                        <!-- Always use JSON viewer for output -->
                        <div
                            class="collapsible-content"
                            [@expandCollapse]="isOutputExpanded ? 'expanded' : 'collapsed'"
                        >
                            <div class="output-content">
                                <app-copy-button [text]="outputJson" />
                                <ngx-json-viewer
                                    [json]="getOutput()"
                                    [expanded]="false"
                                ></ngx-json-viewer>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    styles: `
        .finish-container {
            position: relative;
            background-color: var(--color-nodes-background);
            border-radius: var(--radius-lg);
            padding: var(--message-padding, var(--space-xl));
            box-shadow: 0 4px 12px var(--black-alpha-15);
            border-left: 4px solid var(--blue-500);

            .finish-header {
                display: flex;
                align-items: center;
                cursor: pointer;
                user-select: none;

                .play-arrow {
                    margin-right: var(--space-lg);
                    display: flex;
                    align-items: center;

                    app-svg-icon {
                        color: var(--blue-500);
                    }
                }

                .icon-container {
                    width: 36px;
                    height: 36px;
                    border-radius: 50%;
                    background-color: var(--blue-500);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin-right: var(--space-xl);
                    flex-shrink: 0;

                    app-svg-icon {
                        color: var(--gray-900);
                    }
                }

                h3 {
                    color: var(--color-text-primary);
                    font-size: var(--font-size-xl);
                    font-weight: var(--font-weight-semibold);
                    margin: 0;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    max-width: 100%;

                    .project-name {
                        color: var(--blue-500);
                        font-weight: var(--font-weight-regular);
                        margin-right: var(--space-xs);
                    }
                }
            }

            .finish-content {
                display: flex;
                flex-direction: column;
                gap: var(--space-sm);
                padding-left: 5.5rem;
                margin-top: var(--space-xl);
                overflow: hidden;
            }

            /* Section styling */
            .section-heading {
                font-weight: var(--font-weight-medium);
                color: var(--color-text-secondary);
                margin-bottom: var(--space-lg);
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;

                app-svg-icon {
                    margin-right: var(--space-sm);
                    color: var(--blue-500);
                    margin-left: -3px;
                }
            }

            /* Collapsible content container */
            .collapsible-content {
                overflow: hidden;
                position: relative;

                &.ng-animating {
                    overflow: hidden;
                }
            }

            .variables-content,
            .output-content {
                position: relative;
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: var(--radius-lg);
                padding: var(--space-xl);
                margin-left: var(--space-2xl);
                max-height: 400px;
                overflow: auto;

                &:hover app-copy-button {
                    opacity: 1;
                }
            }
        }
    `,
})
export class FinishMessageComponent implements OnInit {
    @Input() message!: GraphMessage;
    @Input() project: GetProjectRequest | null = null;

    isMessageExpanded = false;
    isOutputExpanded = true;
    isVariablesExpanded = false;

    ngOnInit() {}

    get variablesJson(): string {
        return JSON.stringify(this.getVariables(), null, 2);
    }

    get outputJson(): string {
        return JSON.stringify(this.getOutput(), null, 2);
    }

    toggleMessage(): void {
        this.isMessageExpanded = !this.isMessageExpanded;
    }

    toggleSection(section: 'output' | 'variables'): void {
        if (section === 'output') {
            this.isOutputExpanded = !this.isOutputExpanded;
        } else if (section === 'variables') {
            this.isVariablesExpanded = !this.isVariablesExpanded;
        }
    }

    getFinishData(): FinishMessageData | null {
        if (this.message.message_data && this.message.message_data.message_type === 'finish') {
            return this.message.message_data as FinishMessageData;
        }
        return null;
    }

    // Get output directly for JSON viewer
    getOutput(): Record<string, unknown> {
        const finishData = this.getFinishData();
        if (!finishData || !finishData.output) {
            return {}; // Return empty object if no output
        }
        return finishData.output;
    }

    // Variables handling
    hasVariables(): boolean {
        const finishData = this.getFinishData();
        if (!finishData || !finishData.state) return false;

        return !!finishData.state['variables'] && Object.keys(finishData.state['variables']).length > 0;
    }

    getVariables(): Record<string, unknown> {
        const finishData = this.getFinishData();
        if (!finishData || !finishData.state || !finishData.state['variables']) return {};

        return finishData.state['variables'] || {};
    }
}
