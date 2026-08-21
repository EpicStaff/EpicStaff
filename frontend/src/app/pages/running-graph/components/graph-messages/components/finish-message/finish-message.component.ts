import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input, OnInit } from '@angular/core';
import { JsonViewerComponent } from '@shared/components';

import { GetProjectRequest } from '../../../../../../features/projects/models/project.model';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import {
    FinishMessageData,
    FinishStopReason,
    GraphMessage,
    MessageType,
} from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-finish-message',
    imports: [CommonModule, JsonViewerComponent, AppSvgIconComponent, CopyButtonComponent],
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
                    @if (project && project.name) {
                        <span class="project-name">{{ project.name }}</span>
                    }
                    @if (!project || !project.name) {
                        <span>Default Project</span>
                    }
                    finished
                </h3>
                @if (getStopReason(); as stopReason) {
                    <span
                        class="stop-reason-badge"
                        [ngClass]="'stop-reason-badge--' + getStopReason()"
                    >
                        {{ getStopReasonLabel(stopReason) }}
                    </span>
                }
            </div>

            <!-- Collapsible Finish Content -->
            <div
                class="collapsible-content grid-collapsible"
                [class.expanded]="isMessageExpanded"
            >
                <div class="finish-content">
                    <!-- Variables Section -->
                    @if (hasVariables()) {
                        <div class="variables-container">
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
                                class="collapsible-content grid-collapsible"
                                [class.expanded]="isVariablesExpanded"
                            >
                                <div class="variables-content">
                                    <app-copy-button [text]="variablesJson" />
                                    <app-json-viewer
                                        [json]="getVariables()"
                                        [expanded]="false"
                                    ></app-json-viewer>
                                </div>
                            </div>
                        </div>
                    }

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
                            class="collapsible-content grid-collapsible"
                            [class.expanded]="isOutputExpanded"
                        >
                            <div class="output-content">
                                <app-copy-button [text]="outputJson" />
                                <app-json-viewer
                                    [json]="getOutput()"
                                    [expanded]="false"
                                ></app-json-viewer>
                            </div>
                        </div>
                    </div>

                    <!-- Schema-validated output (schema_satisfied): parsed JSON view of output.message -->
                    @if (getSchemaOutput(); as schemaOutput) {
                        <div class="schema-output-container">
                            <div class="section-heading">
                                <app-svg-icon
                                    icon="caret-down-filled"
                                    size="1rem"
                                />
                                Schema-Validated Output
                            </div>
                            <div class="output-content">
                                <app-copy-button [text]="schemaOutputJson" />
                                <app-json-viewer
                                    [json]="schemaOutput"
                                    [expanded]="true"
                                ></app-json-viewer>
                            </div>
                        </div>
                    }
                </div>
            </div>
        </div>
    `,
    changeDetection: ChangeDetectionStrategy.Eager,
    styles: `
        .finish-container {
            position: relative;
            background-color: var(--color-nodes-background);
            border-radius: 8px;
            padding: var(--message-padding, 1.25rem);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            border-left: 4px solid #5672cd;

            .finish-header {
                display: flex;
                align-items: center;
                cursor: pointer;
                user-select: none;

                .play-arrow {
                    margin-right: 16px;
                    display: flex;
                    align-items: center;

                    app-svg-icon {
                        color: #5672cd;
                    }
                }

                .icon-container {
                    width: 36px;
                    height: 36px;
                    border-radius: 50%;
                    background-color: #5672cd;
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
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    max-width: 100%;

                    .project-name {
                        color: #5672cd;
                        font-weight: 400;
                        margin-right: 5px;
                    }
                }

                .stop-reason-badge {
                    margin-left: 12px;
                    padding: 0.15rem 0.6rem;
                    border-radius: 999px;
                    font-size: 0.75rem;
                    font-weight: 600;
                    white-space: nowrap;
                    flex-shrink: 0;

                    &.stop-reason-badge--completed,
                    &.stop-reason-badge--schema_satisfied {
                        color: #30a46c;
                        background-color: rgba(48, 164, 108, 0.15);
                    }

                    &.stop-reason-badge--max_iter_reached {
                        color: #fbbf24;
                        background-color: rgba(251, 191, 36, 0.15);
                    }
                }
            }

            .finish-content {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
                padding-left: 5.5rem;
                margin-top: 1.25rem;
                overflow: hidden;
            }

            /* Section styling */
            .section-heading {
                font-weight: 500;
                color: var(--gray-300);
                margin-bottom: 1rem;
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;

                app-svg-icon {
                    margin-right: 8px;
                    color: #5672cd;
                    margin-left: -3px;
                }
            }

            /* Collapsible content container */
            .collapsible-content {
                overflow: hidden;
                position: relative;
            }

            .variables-content,
            .output-content {
                position: relative;
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                padding: 1.25rem;
                margin-left: 1.5rem;
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

    get schemaOutputJson(): string {
        return JSON.stringify(this.getSchemaOutput(), null, 2);
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
        if (this.message.message_data && this.message.message_data.message_type === MessageType.FINISH) {
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

    // TaskNode / AgentNode finish payloads report a `stop_reason`; other node types don't
    // set it, so this stays null and the template renders exactly as before (no regression).
    getStopReason(): FinishStopReason | null {
        return this.getFinishData()?.output?.stop_reason ?? null;
    }

    getStopReasonLabel(stopReason: FinishStopReason): string {
        switch (stopReason) {
            case 'schema_satisfied':
                return 'Output matches schema';
            case 'max_iter_reached':
                return 'Max iterations reached';
            case 'completed':
            default:
                return 'Completed';
        }
    }

    // When stop_reason is 'schema_satisfied', output.message is a JSON string (the task had
    // an output schema) — parse it for a formatted JSON view. Returns null when not applicable
    // or when the message isn't valid JSON (falls back to the generic Final Output section).
    getSchemaOutput(): Record<string, unknown> | unknown[] | null {
        if (this.getStopReason() !== 'schema_satisfied') return null;

        const message = this.getFinishData()?.output?.message;
        if (typeof message !== 'string') return null;

        try {
            const parsed: unknown = JSON.parse(message);
            if (parsed !== null && typeof parsed === 'object') {
                return parsed as Record<string, unknown> | unknown[];
            }
            return null;
        } catch {
            return null;
        }
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
