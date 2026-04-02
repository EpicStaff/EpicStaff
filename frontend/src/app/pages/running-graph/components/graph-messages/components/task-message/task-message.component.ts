import { CommonModule } from '@angular/common';
import { Component, Input, OnInit } from '@angular/core';
import { NgxJsonViewerModule } from 'ngx-json-viewer';
import { MarkdownModule } from 'ngx-markdown';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { GraphMessage, TaskMessageData } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-task-message',
    standalone: true,
    imports: [CommonModule, MarkdownModule, NgxJsonViewerModule],
    animations: [expandCollapseAnimation],
    template: `
        <div class="agent-flow-container">
            <!-- Task Message Header with Toggle -->
            <div class="agent-header" (click)="toggleMessage()">
                <div class="play-arrow">
                    <i class="ti" [ngClass]="isMessageExpanded ? 'ti-caret-down-filled' : 'ti-caret-right-filled'"></i>
                </div>
                <div class="icon-container">
                    <i class="ti ti-list-check"></i>
                </div>
                <h3>
                    Task <span class="task-name">{{ getTaskName() }}</span> is done
                </h3>
            </div>

            <!-- Collapsible Task Content -->
            <div class="collapsible-content" [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'">
                <div class="agent-content">
                    <!-- Task Details Section -->
                    <div class="details-container" *ngIf="hasDetails()">
                        <div class="section-heading" (click)="toggleSection('details')">
                            <i
                                class="ti"
                                [ngClass]="isDetailsExpanded ? 'ti-caret-down-filled' : 'ti-caret-right-filled'"
                            ></i>
                            Task Details
                        </div>
                        <div
                            class="collapsible-content"
                            [@expandCollapse]="isDetailsExpanded ? 'expanded' : 'collapsed'"
                        >
                            <div class="details-content">
                                <div class="description-section" *ngIf="taskMessageData?.description">
                                    <div class="subsection-heading">Description:</div>
                                    <div class="description-content">
                                        {{ taskMessageData?.description }}
                                    </div>
                                </div>

                                <div class="expected-output-section" *ngIf="taskMessageData?.expected_output">
                                    <div class="subsection-heading">Expected Output:</div>
                                    <div class="expected-output-content">
                                        {{ taskMessageData?.expected_output }}
                                    </div>
                                </div>

                                <div class="agent-section" *ngIf="taskMessageData?.agent">
                                    <div class="subsection-heading">Assigned To:</div>
                                    <div class="agentData-content">
                                        {{ taskMessageData?.agent }}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Result Section -->
                    <div class="raw-container" *ngIf="hasRawData()">
                        <div class="section-heading" (click)="toggleSection('raw')">
                            <i
                                class="ti"
                                [ngClass]="isRawExpanded ? 'ti-caret-down-filled' : 'ti-caret-right-filled'"
                            ></i>
                            Result
                        </div>
                        <div class="collapsible-content" [@expandCollapse]="isRawExpanded ? 'expanded' : 'collapsed'">
                            <div class="result-content">
                                <!-- JSON Viewer when raw data is valid JSON -->
                                <ngx-json-viewer
                                    *ngIf="isValidJson(getRawData())"
                                    [json]="parsedRawData"
                                    [expanded]="false"
                                ></ngx-json-viewer>

                                <!-- Markdown Output when raw data is not valid JSON -->
                                <div
                                    class="markdown-content"
                                    [ngClass]="{ collapsed: isCollapsed && shouldShowToggle() }"
                                    *ngIf="!isValidJson(getRawData())"
                                >
                                    <markdown [data]="getRawData()"></markdown>
                                </div>
                                <button
                                    *ngIf="shouldShowToggle() && isRawExpanded && !isValidJson(getRawData())"
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
        </div>
    `,
    styles: `
        .agent-flow-container {
            background-color: var(--color-nodes-background);
            border-radius: 8px;
            padding: 1.25rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            border-left: 4px solid #30a46c;
        }

        .agent-header {
            display: flex;
            align-items: center;
            cursor: pointer;
            user-select: none;

            .play-arrow {
                margin-right: 16px;
                display: flex;
                align-items: center;

                i {
                    color: #30a46c;
                    font-size: 1.1rem;
                    transition: transform 0.3s ease;
                }
            }

            .icon-container {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background-color: #30a46c;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 20px;
                flex-shrink: 0;

                i {
                    color: var(--gray-900);
                    font-size: 1.25rem;
                }
            }

            h3 {
                color: var(--gray-100);
                font-size: 1.1rem;
                font-weight: 600;
                margin: 0;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                max-width: 100%;

                .task-name {
                    color: #30a46c;
                    font-weight: 400;
                    margin: 0 5px;
                }
            }
        }

        .agent-content {
            display: flex;
            flex-direction: column;
            gap: 1rem;
            padding-left: 5.5rem;
            margin-top: 1.25rem;
            overflow: hidden;
        }

        /* Collapsible content container */
        .collapsible-content {
            overflow: hidden;
            position: relative;

            &.ng-animating {
                overflow: hidden;
            }
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

            i {
                margin-right: 8px;
                color: #30a46c;
                font-size: 1.1rem;
                margin-left: -3px;
                transition: transform 0.3s ease;
            }
        }

        .details-content {
            background-color: var(--gray-800);
            border: 1px solid var(--gray-750);
            border-radius: 8px;
            padding: 1rem;
            color: var(--gray-200);
            margin-left: 23px;

            .subsection-heading {
                font-weight: 500;
                color: #30a46c;
                margin-bottom: 0.5rem;
                margin-top: 1rem;

                &:first-child {
                    margin-top: 0;
                }
            }

            .description-content,
            .expected-output-content,
            .agentData-content {
                padding: 0.5rem;
                background-color: var(--gray-850);
                border-radius: 6px;
            }

            .expected-output-section,
            .agent-section {
                margin-top: 1rem;
            }
        }

        .result-content {
            background-color: var(--gray-800);
            border: 1px solid var(--gray-750);
            border-radius: 8px;
            padding: 1rem;
            color: var(--gray-200);
            margin-left: 23px;
            overflow-y: auto;
            max-height: 400px;
        }

        .markdown-content {
            transition: max-height 0.3s ease;

            &.collapsed {
                max-height: 200px;
                overflow-y: hidden;
            }
        }

        .toggle-button {
            background-color: transparent;
            border: none;
            color: #30a46c;
            font-size: 0.85rem;
            cursor: pointer;
            padding: 0.5rem;
            text-align: center;
            width: 100%;
            margin-top: 0.25rem;

            &:hover {
                text-decoration: underline;
            }
        }

        pre {
            margin: 0;
        }
    `,
})
export class TaskMessageComponent implements OnInit {
    @Input() message!: GraphMessage;
    isMessageExpanded = false;
    isDetailsExpanded = false;
    isRawExpanded = true;
    isCollapsed = true;
    parsedRawData: unknown = null;

    ngOnInit() {
        // Attempt to parse the raw data as JSON during initialization
        if (this.hasRawData()) {
            this.tryParseRawJson();
        }
    }

    toggleMessage(): void {
        this.isMessageExpanded = !this.isMessageExpanded;
    }

    toggleSection(section: 'details' | 'raw'): void {
        if (section === 'details') {
            this.isDetailsExpanded = !this.isDetailsExpanded;
        } else if (section === 'raw') {
            this.isRawExpanded = !this.isRawExpanded;
        }
    }

    toggleCollapse(): void {
        this.isCollapsed = !this.isCollapsed;
    }

    shouldShowToggle(): boolean {
        if (!this.getRawData()) return false;

        // Show toggle button if content is longer than approximately 5 lines
        return this.getRawData().split('\n').length > 5 || this.getRawData().length > 500;
    }

    getTaskName(): string {
        return this.taskMessageData?.name || 'Task';
    }

    hasDetails(): boolean {
        return !!(
            this.taskMessageData?.description ||
            this.taskMessageData?.expected_output ||
            this.taskMessageData?.agent
        );
    }

    hasRawData(): boolean {
        return !!this.getRawData() && this.getRawData() !== '';
    }

    getRawData(): string {
        return this.taskMessageData?.raw || '';
    }

    isValidJson(str: string): boolean {
        try {
            JSON.parse(str);
            return true;
        } catch {
            return false;
        }
    }

    tryParseRawJson(): void {
        if (this.hasRawData()) {
            try {
                this.parsedRawData = JSON.parse(this.getRawData());
            } catch {
                this.parsedRawData = null;
            }
        }
    }

    get taskMessageData(): TaskMessageData | null {
        if (this.message.message_data && this.message.message_data.message_type === 'task') {
            return this.message.message_data as TaskMessageData;
        }
        return null;
    }
}
