import { CommonModule } from '@angular/common';
import { Component, Input, OnInit } from '@angular/core';
import { NgxJsonViewerModule } from 'ngx-json-viewer';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { FormatExecutionDataPipe } from '../../../../../../shared/pipes/format-execution-data.pipe';
import { GraphMessage, MessageType, PythonMessageData } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-python-message',
    standalone: true,
    imports: [CommonModule, NgxJsonViewerModule, FormatExecutionDataPipe, AppSvgIconComponent],
    animations: [expandCollapseAnimation],
    template: `
        <div class="python-flow-container">
            <!-- Python Message Header with Toggle -->
            <div class="python-header" (click)="toggleMessage()">
                <div class="play-arrow">
                    <app-svg-icon [icon]="isMessageExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1.1rem" />
                </div>
                <div class="icon-container">
                    <app-svg-icon icon="brand-python" size="1.25rem" />
                </div>
                <h3>Python Code Execution</h3>
            </div>

            <!-- Collapsible Python Content -->
            <div class="collapsible-content" [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'">
                <div class="python-content">
                    <!-- Code Section -->
                    <div class="code-container" *ngIf="hasCode()">
                        <div class="section-heading" (click)="toggleSection('code')">
                            <app-svg-icon [icon]="isCodeExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1.1rem" />
                            Python Code
                        </div>
                        <div class="collapsible-content" [@expandCollapse]="isCodeExpanded ? 'expanded' : 'collapsed'">
                            <div class="code-wrapper">
                                <div class="result-content">
                                    <pre>{{ getCode() }}</pre>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Input Section -->
                    <div class="input-container" *ngIf="hasInput()">
                        <div class="section-heading" (click)="toggleSection('input')">
                            <app-svg-icon [icon]="isInputExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1.1rem" />
                            Input
                        </div>
                        <div class="collapsible-content" [@expandCollapse]="isInputExpanded ? 'expanded' : 'collapsed'">
                            <div class="input-wrapper">
                                <div class="result-content">
                                    <ngx-json-viewer
                                        *ngIf="getParsedInput() && isValidJson(getInput())"
                                        [json]="getParsedInput()"
                                        [expanded]="false"
                                    ></ngx-json-viewer>
                                    <pre *ngIf="!isValidJson(getInput())">{{ getInput() }}</pre>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Output Section -->
                    <div class="output-container" *ngIf="hasOutput()">
                        <div class="section-heading" (click)="toggleSection('output')">
                            <app-svg-icon [icon]="isOutputExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1.1rem" />
                            Output
                        </div>
                        <div
                            class="collapsible-content"
                            [@expandCollapse]="isOutputExpanded ? 'expanded' : 'collapsed'"
                        >
                            <div class="output-wrapper">
                                <div
                                    class="result-content"
                                    [ngClass]="{
                                        collapsed: isCollapsed && shouldShowToggle(),
                                    }"
                                >
                                    <pre>{{ getOutput() }}</pre>
                                </div>
                                <button
                                    *ngIf="shouldShowToggle() && isOutputExpanded"
                                    class="toggle-button"
                                    (click)="toggleCollapse()"
                                >
                                    {{ isCollapsed ? 'Show more' : 'Show less' }}
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- Error Section -->
                    <div class="error-container" *ngIf="hasError()">
                        <div class="section-heading" (click)="toggleSection('error')">
                            <app-svg-icon [icon]="isErrorExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1.1rem" />
                            Error
                        </div>
                        <div class="collapsible-content" [@expandCollapse]="isErrorExpanded ? 'expanded' : 'collapsed'">
                            <div class="error-wrapper">
                                <div class="result-content error-content">
                                    <pre>{{ getError() }}</pre>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Raw Data Section -->
                    <div class="raw-data-container">
                        <div class="section-heading" (click)="toggleSection('rawData')">
                            <app-svg-icon [icon]="isRawDataExpanded ? 'caret-down-filled' : 'caret-right-filled'" size="1.1rem" />
                            Raw Execution Data
                        </div>
                        <div
                            class="collapsible-content"
                            [@expandCollapse]="isRawDataExpanded ? 'expanded' : 'collapsed'"
                        >
                            <div class="raw-data-wrapper">
                                <div class="raw-data-content">
                                    <ngx-json-viewer
                                        [json]="getExecutionData() | formatExecutionData"
                                        [expanded]="false"
                                    ></ngx-json-viewer>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            .python-flow-container {
                background-color: var(--color-nodes-background);
                border-radius: 8px;
                padding: 1.25rem;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border-left: 4px solid #ffcf3f;
            }

            .python-header {
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
                    color: #ffcf3f;
                }
            }

            .icon-container {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background-color: #ffcf3f;
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

            .python-content {
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
            }

            .collapsible-content.ng-animating {
                overflow: hidden;
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
            }

            .section-heading app-svg-icon {
                margin-right: 8px;
                color: #ffcf3f;
                margin-left: -3px;
            }

            .code-wrapper,
            .input-wrapper,
            .output-wrapper,
            .error-wrapper,
            .raw-data-wrapper {
                margin-left: 23px;
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
            }

            .result-content.collapsed {
                max-height: 200px;
                overflow: hidden;
            }

            .raw-data-content {
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                padding: 1rem;
                overflow: auto;
                max-height: 600px;
            }

            .raw-data-content ::ng-deep ngx-json-viewer,
            .raw-data-content ::ng-deep .ngx-json-viewer {
                display: inline-block;
                min-width: 100%;
                white-space: pre-wrap;
            }

            .error-content {
                color: #ff6b6b;
            }

            .toggle-button {
                background-color: transparent;
                border: none;
                color: #ffcf3f;
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
            }
        `,
    ],
})
export class PythonMessageComponent implements OnInit {
    @Input() message!: GraphMessage;
    isMessageExpanded = false;
    isCodeExpanded = true;
    isInputExpanded = true;
    isOutputExpanded = true;
    isErrorExpanded = true;
    isRawDataExpanded = false; // Collapsed by default since it's less important
    isCollapsed = true;
    parsedInput: unknown = null;

    ngOnInit() {
        if (this.hasInput()) {
            this.tryParseJson();
        }
    }

    toggleMessage(): void {
        this.isMessageExpanded = !this.isMessageExpanded;
        if (this.isMessageExpanded) {
            this.isRawDataExpanded = true;
        }
    }

    toggleSection(section: 'code' | 'input' | 'output' | 'error' | 'rawData'): void {
        if (section === 'code') {
            this.isCodeExpanded = !this.isCodeExpanded;
        } else if (section === 'input') {
            this.isInputExpanded = !this.isInputExpanded;
        } else if (section === 'output') {
            this.isOutputExpanded = !this.isOutputExpanded;
        } else if (section === 'error') {
            this.isErrorExpanded = !this.isErrorExpanded;
        } else if (section === 'rawData') {
            this.isRawDataExpanded = !this.isRawDataExpanded;
        }
    }

    getExecutionData(): Record<string, unknown> {
        if (!this.message.message_data) return {};

        // Type guard to check if message_data is PythonMessageData
        if (this.message.message_data.message_type === MessageType.PYTHON) {
            return (this.message.message_data as PythonMessageData).python_code_execution_data || {};
        }

        return {};
    }

    hasCode(): boolean {
        const data = this.getExecutionData();
        return !!data['code'];
    }

    getCode(): string {
        const data = this.getExecutionData();
        return typeof data['code'] === 'string' ? data['code'] : '';
    }

    hasInput(): boolean {
        const data = this.getExecutionData();
        return !!data['input'];
    }

    getInput(): string {
        const data = this.getExecutionData();
        return typeof data['input'] === 'string' ? data['input'] : JSON.stringify(data['input'], null, 2);
    }

    tryParseJson(): void {
        if (this.hasInput()) {
            try {
                const data = this.getExecutionData();
                this.parsedInput = typeof data['input'] === 'string' ? JSON.parse(data['input']) : data['input'];
            } catch {
                this.parsedInput = null;
            }
        }
    }

    isValidJson(str: string): boolean {
        try {
            JSON.parse(str);
            return true;
        } catch {
            return false;
        }
    }

    getParsedInput() {
        if (!this.parsedInput) {
            this.tryParseJson();
        }
        return this.parsedInput;
    }

    formatJson(jsonString: string): string {
        try {
            const parsed = JSON.parse(jsonString);
            return JSON.stringify(parsed, null, 2);
        } catch {
            return jsonString;
        }
    }

    hasOutput(): boolean {
        const data = this.getExecutionData();
        return !!data['output'];
    }

    getOutput(): string {
        const data = this.getExecutionData();
        return typeof data['output'] === 'string' ? data['output'] : '';
    }

    hasError(): boolean {
        const data = this.getExecutionData();
        return !!data['error'];
    }

    getError(): string {
        const data = this.getExecutionData();
        return typeof data['error'] === 'string' ? data['error'] : '';
    }

    toggleCollapse(): void {
        this.isCollapsed = !this.isCollapsed;
    }

    shouldShowToggle(): boolean {
        if (!this.hasOutput()) return false;
        const output = this.getOutput();
        // Show toggle button if content is longer than approximately 5 lines
        return output.split('\n').length > 5 || output.length > 500;
    }
}
