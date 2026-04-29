import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output, ViewEncapsulation } from '@angular/core';
import { NgxJsonViewerModule } from 'ngx-json-viewer';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GraphMessage, MessageType, StartSubflowMessageData } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-subgraph-start-message',
    standalone: true,
    imports: [CommonModule, NgxJsonViewerModule, AppSvgIconComponent],
    encapsulation: ViewEncapsulation.Emulated,
    animations: [expandCollapseAnimation],
    template: `
        <div class="subgraph-start-container">
            <div
                class="subgraph-start-header"
                (click)="toggleMessage()"
            >
                <div
                    class="play-arrow"
                    *ngIf="hasContent()"
                >
                    <app-svg-icon
                        [icon]="isMessageExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                        size="1.1rem"
                    />
                </div>
                <div class="icon-container">
                    <app-svg-icon
                        icon="hierarchy-2"
                        size="1.25rem"
                    />
                </div>
                <h3>
                    <span class="node-name">{{ message.name }}</span> subgraph started {{ subgraphName }}
                </h3>

                <button
                    class="view-nested-button"
                    type="button"
                    *ngIf="showViewNestedMessages"
                    (click)="onViewNestedMessages($event)"
                    [class.show-nested-btn--open]="isNestedMessagesOpen"
                >
                    <div
                        class="play-nested-arrow"
                        [class.play-nested-arrow--open]="isNestedMessagesOpen"
                    >
                        <app-svg-icon
                            icon="caret-right-filled"
                            size="1rem"
                        />
                    </div>
                    <svg
                        class="view-nested-icon"
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 2341 1024"
                        [class.view-nested-icon--open]="isNestedMessagesOpen"
                    >
                        <path
                            d="M87.771 0h2165.029c48.475 0 87.771 39.297 87.771 87.771v117.029c0 48.475-39.297 87.771-87.771 87.771h-2165.029c-48.475 0-87.771-39.297-87.771-87.771v-117.029c0-48.475 39.297-87.771 87.771-87.771z"
                        ></path>
                        <path
                            d="M438.857 438.857h1828.571c40.396 0 73.143 32.747 73.143 73.143v73.143c0 40.396-32.747 73.143-73.143 73.143h-1828.571c-40.396 0-73.143-32.747-73.143-73.143v-73.143c0-40.396 32.747-73.143 73.143-73.143z"
                        ></path>
                        <path
                            d="M438.857 804.571h1828.571c40.396 0 73.143 32.747 73.143 73.143v73.143c0 40.396-32.747 73.143-73.143 73.143h-1828.571c-40.396 0-73.143-32.747-73.143-73.143v-73.143c0-40.396 32.747-73.143 73.143-73.143z"
                        ></path>
                    </svg>
                </button>
            </div>

            <!-- Collapsible Content -->
            <div
                class="collapsible-content"
                [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
            >
                <div class="subgraph-start-content">
                    <!-- Input Parameters Section -->
                    <div
                        class="input-container"
                        *ngIf="hasInput()"
                    >
                        <div
                            class="section-heading"
                            (click)="toggleInputs($event)"
                        >
                            <app-svg-icon
                                [icon]="isInputsExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                                size="1.1rem"
                            />
                            Input Parameters
                        </div>
                        <div
                            class="collapsible-content"
                            [@expandCollapse]="isInputsExpanded ? 'expanded' : 'collapsed'"
                        >
                            <div class="input-content">
                                <ngx-json-viewer
                                    [json]="getInput()"
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
                                size="1.1rem"
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
            .subgraph-start-container {
                position: relative;
                background-color: var(--color-nodes-background);
                border-radius: 8px;
                padding: 1.25rem;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border-left: 4px solid #00bfa5;
            }

            .subgraph-start-header {
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

            .subgraph-start-content {
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
            }

            .section-heading app-svg-icon {
                margin-right: 8px;
                color: #00bfa5;
                margin-left: -3px;
            }

            .input-container,
            .variables-container,
            .state-history-container {
                margin-bottom: 0.5rem;
            }

            .input-content,
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

            .view-nested-button {
                margin-left: auto;
                background-color: rgb(0, 191, 165);
                color: rgb(255, 255, 255);
                border: 2px solid rgba(0, 191, 165, 0.4);
                border-radius: 6px;
                padding: 0.5rem 0.75rem;
                font-weight: 500;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
                cursor: pointer;
                transition:
                    background-color 0.2s ease,
                    border-color 0.2s ease;
            }

            .view-nested-button:hover {
                background-color: transparent;
                color: rgb(0, 191, 165);
                border-color: rgb(0, 191, 165);
            }

            .show-nested-btn--open {
                background-color: transparent;
            }

            .play-nested-arrow {
                margin-top: 2px;
                display: inline-block;
                transform: rotate(0deg);
                transition: transform 0.2s ease;
                color: white;
            }

            .play-nested-arrow--open {
                transition:
                    transform 0.2s ease,
                    color 0.2s ease;
                transform: rotate(90deg);
                color: rgb(0, 191, 165);
            }

            .view-nested-icon {
                transition:
                    transform 0.2s ease,
                    fill 0.2s ease;
                height: 1.1rem;
                display: block;
                fill: white;
            }

            .view-nested-icon--open {
                fill: rgb(0, 191, 165);
            }
        `,
    ],
})
export class SubgraphStartMessageComponent {
    @Input() message!: GraphMessage;
    @Input() subgraphName: string | null = null;
    @Input() showViewNestedMessages = true;
    @Input() isNestedMessagesOpen = false;
    @Output() viewNestedMessages = new EventEmitter<void>();
    isMessageExpanded = false;
    isInputsExpanded = true;
    isVariablesExpanded = true;

    toggleMessage(): void {
        if (!this.hasContent()) return;
        this.isMessageExpanded = !this.isMessageExpanded;
    }

    onViewNestedMessages(event: Event): void {
        event.stopPropagation();
        this.viewNestedMessages.emit();
    }

    toggleInputs(event: Event): void {
        event.stopPropagation();
        this.isInputsExpanded = !this.isInputsExpanded;
    }

    toggleVariables(event: Event): void {
        event.stopPropagation();
        this.isVariablesExpanded = !this.isVariablesExpanded;
    }

    hasContent(): boolean {
        return this.hasInput() || this.hasVariables();
    }

    hasInput(): boolean {
        const input = this.getInput();
        return input && Object.keys(input).length > 0;
    }

    hasVariables(): boolean {
        const variables = this.getVariables();
        return variables && Object.keys(variables).length > 0;
    }

    getInput(): Record<string, unknown> {
        if (!this.message.message_data) return {};

        if (
            this.message.message_data.message_type === MessageType.SUBGRAPH_START &&
            'input' in this.message.message_data
        ) {
            return (this.message.message_data as StartSubflowMessageData).input || {};
        }

        return {};
    }

    getVariables(): Record<string, unknown> {
        if (!this.message.message_data) return {};

        if (
            this.message.message_data.message_type === MessageType.SUBGRAPH_START &&
            'state' in this.message.message_data
        ) {
            return (this.message.message_data as StartSubflowMessageData).state?.variables || {};
        }

        return {};
    }

    getStateHistory() {
        if (!this.message.message_data) return [];

        if (
            this.message.message_data.message_type === MessageType.SUBGRAPH_START &&
            'state' in this.message.message_data
        ) {
            return (this.message.message_data as StartSubflowMessageData).state?.state_history || [];
        }

        return [];
    }
}
