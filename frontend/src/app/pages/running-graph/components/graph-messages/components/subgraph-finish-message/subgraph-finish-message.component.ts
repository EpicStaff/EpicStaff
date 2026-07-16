import { CommonModule } from '@angular/common';
import { Component, Input, ViewEncapsulation } from '@angular/core';
import { NgxJsonViewerModule } from 'ngx-json-viewer';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import {
    FinishSubflowMessageData,
    GraphMessage,
    MessageType,
    StateHistoryItem,
} from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-subgraph-finish-message',
    standalone: true,
    imports: [CommonModule, NgxJsonViewerModule, AppSvgIconComponent, CopyButtonComponent],
    encapsulation: ViewEncapsulation.Emulated,
    animations: [expandCollapseAnimation],
    template: `
        <div class="subgraph-finish-container">
            <div
                class="subgraph-finish-header"
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
                        icon="hierarchy-2"
                        size="1rem"
                    />
                </div>
                <h3>
                    <span class="node-name">{{ message.name }}</span> subgraph finished
                </h3>
            </div>

            <!-- Collapsible Content -->
            <div
                class="collapsible-content"
                [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
            >
                <div class="subgraph-finish-content">
                    <!-- Final Output Section -->
                    <div
                        class="output-container"
                        *ngIf="hasOutput()"
                    >
                        <div
                            class="section-heading"
                            (click)="toggleOutput($event)"
                        >
                            <app-svg-icon
                                [icon]="isOutputExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                                size="1rem"
                            />
                            Final Output
                        </div>
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

                    <!-- Variables Section -->
                    <div
                        class="variables-container"
                        *ngIf="hasVariables()"
                    >
                        <div
                            class="section-heading"
                            (click)="toggleVariables($event)"
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

                    <!-- State History Section (commented out) -->
                    <!-- <div class="state-history-container" *ngIf="hasStateHistory()"> ... </div> -->
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            .subgraph-finish-container {
                position: relative;
                background-color: var(--color-nodes-background);
                border-radius: var(--radius-lg);
                padding: var(--space-xl);
                box-shadow: 0 4px 12px var(--black-alpha-15);
                border-left: 4px solid var(--teal-500);
            }

            .subgraph-finish-header {
                display: flex;
                align-items: center;
                cursor: pointer;
                user-select: none;
            }

            .play-arrow {
                margin-right: var(--space-lg);
                display: flex;
                align-items: center;

                app-svg-icon {
                    color: var(--teal-500);
                }
            }

            .icon-container {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background-color: var(--teal-500);
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
            }

            .node-name {
                color: var(--teal-500);
                font-weight: var(--font-weight-regular);
            }

            /* Collapsible content container */
            .collapsible-content {
                overflow: hidden;
                position: relative;
            }

            .collapsible-content.ng-animating {
                overflow: hidden;
            }

            .subgraph-finish-content {
                display: flex;
                flex-direction: column;
                gap: var(--space-lg);
                padding-left: 5.5rem;
                margin-top: var(--space-xl);
            }

            /* Section styling */
            .section-heading {
                font-weight: var(--font-weight-medium);
                color: var(--color-text-secondary);
                margin-bottom: var(--space-sm);
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;

                app-svg-icon {
                    margin-right: var(--space-sm);
                    color: var(--teal-500);
                    margin-left: -3px;
                }
            }

            .output-container,
            .variables-container,
            .state-history-container {
                margin-bottom: var(--space-sm);
            }

            .output-content,
            .variables-content {
                position: relative;
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: var(--radius-lg);
                padding: var(--space-lg);
                overflow: auto;
                max-height: 400px;
                margin-left: 23px;

                &:hover app-copy-button {
                    opacity: 1;
                }
            }

            .state-history-content {
                margin-left: 23px;
                display: flex;
                flex-direction: column;
                gap: var(--space-lg);
            }

            .state-history-item {
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: var(--radius-lg);
                padding: var(--space-lg);
            }

            .state-history-item-header {
                display: flex;
                align-items: center;
                gap: var(--space-md);
                margin-bottom: var(--space-md);
                padding-bottom: var(--space-md);
                border-bottom: 1px solid var(--gray-750);
            }

            .item-index {
                background-color: var(--teal-500);
                color: var(--gray-900);
                font-weight: var(--font-weight-semibold);
                padding: var(--space-2xs) var(--space-sm);
                border-radius: var(--radius-sm);
                font-size: var(--font-size-md);
            }

            .item-name {
                color: var(--color-text-primary);
                font-weight: var(--font-weight-medium);
                flex: 1;
            }

            .item-type {
                color: var(--teal-500);
                font-size: var(--font-size-md);
                background-color: rgba(0, 191, 165, 0.15);
                padding: var(--space-2xs) var(--space-sm);
                border-radius: var(--radius-sm);
            }

            .state-history-item-details {
                display: flex;
                flex-direction: column;
                gap: var(--space-md);
            }

            .detail-section {
                display: flex;
                flex-direction: column;
                gap: var(--space-sm);
            }

            .detail-label {
                color: var(--color-text-secondary);
                font-size: var(--font-size-md);
                font-weight: var(--font-weight-medium);
            }

            .detail-content {
                background-color: var(--gray-850);
                border: 1px solid var(--gray-750);
                border-radius: var(--radius-md);
                padding: var(--space-md);
                overflow: auto;
                max-height: 300px;
            }
        `,
    ],
})
export class SubgraphFinishMessageComponent {
    @Input() message!: GraphMessage;
    isMessageExpanded = false;
    isOutputExpanded = true;
    isVariablesExpanded = false;
    isStateHistoryExpanded = true;

    get outputJson(): string {
        return JSON.stringify(this.getOutput(), null, 2);
    }

    get variablesJson(): string {
        return JSON.stringify(this.getVariables(), null, 2);
    }

    toggleMessage(): void {
        this.isMessageExpanded = !this.isMessageExpanded;
    }

    toggleOutput(event: Event): void {
        event.stopPropagation();
        this.isOutputExpanded = !this.isOutputExpanded;
    }

    toggleVariables(event: Event): void {
        event.stopPropagation();
        this.isVariablesExpanded = !this.isVariablesExpanded;
    }

    toggleStateHistory(event: Event): void {
        event.stopPropagation();
        this.isStateHistoryExpanded = !this.isStateHistoryExpanded;
    }

    hasOutput(): boolean {
        const output = this.getOutput();
        if (output == null) return false;
        return typeof output === 'object' ? Object.keys(output).length > 0 : true;
    }

    hasVariables(): boolean {
        const variables = this.getVariables();
        return variables && Object.keys(variables).length > 0;
    }

    hasStateHistory(): boolean {
        const stateHistory = this.getStateHistory();
        return stateHistory && stateHistory.length > 0;
    }

    getOutput(): Record<string, unknown> | null {
        if (!this.message.message_data) return null;

        if (
            this.message.message_data.message_type === MessageType.SUBGRAPH_FINISH &&
            'output' in this.message.message_data
        ) {
            return (this.message.message_data as FinishSubflowMessageData).output;
        }

        return null;
    }

    getVariables(): Record<string, unknown> {
        if (!this.message.message_data) return {};

        if (
            this.message.message_data.message_type === MessageType.SUBGRAPH_FINISH &&
            'state' in this.message.message_data
        ) {
            return (this.message.message_data as FinishSubflowMessageData).state?.variables || {};
        }

        return {};
    }

    getStateHistory() {
        if (!this.message.message_data) return [];

        if (
            this.message.message_data.message_type === MessageType.SUBGRAPH_FINISH &&
            'state' in this.message.message_data
        ) {
            return (this.message.message_data as FinishSubflowMessageData).state?.state_history || [];
        }

        return [];
    }

    getStateHistoryLength(): number {
        return this.getStateHistory().length;
    }

    hasItemInput(item: StateHistoryItem): boolean {
        return item.input && Object.keys(item.input).length > 0;
    }

    hasItemOutput(item: StateHistoryItem): boolean {
        return item.output && Object.keys(item.output).length > 0;
    }

    hasItemVariables(item: StateHistoryItem): boolean {
        return item.variables && Object.keys(item.variables).length > 0;
    }

    hasItemAdditionalData(item: StateHistoryItem): boolean {
        return item.additional_data && Object.keys(item.additional_data).length > 0;
    }
}
