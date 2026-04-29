import { CommonModule } from '@angular/common';
import { Component, Input, ViewEncapsulation } from '@angular/core';
import { NgxJsonViewerModule } from 'ngx-json-viewer';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import {
    FinishSubflowMessageData,
    GraphMessage,
    MessageType,
    StateHistoryItem,
} from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-subgraph-finish-message',
    standalone: true,
    imports: [CommonModule, NgxJsonViewerModule, AppSvgIconComponent],
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
                border-radius: 8px;
                padding: 1.25rem;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border-left: 4px solid #00bfa5;
            }

            .subgraph-finish-header {
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
                    color: #00bfa5;
                }
            }

            .icon-container {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background-color: #00bfa5;
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

            .node-name {
                color: #00bfa5;
                font-weight: 400;
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
                    color: #00bfa5;
                    margin-left: -3px;
                }
            }

            .output-container,
            .variables-container,
            .state-history-container {
                margin-bottom: 0.5rem;
            }

            .output-content,
            .variables-content {
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                padding: 1rem;
                overflow: auto;
                max-height: 400px;
                margin-left: 23px;
            }

            .state-history-content {
                margin-left: 23px;
                display: flex;
                flex-direction: column;
                gap: 1rem;
            }

            .state-history-item {
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                padding: 1rem;
            }

            .state-history-item-header {
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin-bottom: 0.75rem;
                padding-bottom: 0.75rem;
                border-bottom: 1px solid var(--gray-750);
            }

            .item-index {
                background-color: #00bfa5;
                color: var(--gray-900);
                font-weight: 600;
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
                font-size: 0.85rem;
            }

            .item-name {
                color: var(--gray-100);
                font-weight: 500;
                flex: 1;
            }

            .item-type {
                color: #00bfa5;
                font-size: 0.85rem;
                background-color: rgba(0, 191, 165, 0.15);
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
            }

            .state-history-item-details {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
            }

            .detail-section {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .detail-label {
                color: var(--gray-300);
                font-size: 0.9rem;
                font-weight: 500;
            }

            .detail-content {
                background-color: var(--gray-850);
                border: 1px solid var(--gray-750);
                border-radius: 6px;
                padding: 0.75rem;
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
