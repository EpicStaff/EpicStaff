import { ChangeDetectionStrategy, Component, Input, ViewEncapsulation } from '@angular/core';
import { AppSvgIconComponent, CopyButtonComponent, JsonViewerComponent } from '@shared/components';

import { GraphMessage, MessageType } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-start-message',
    imports: [JsonViewerComponent, AppSvgIconComponent, CopyButtonComponent],
    encapsulation: ViewEncapsulation.Emulated,
    template: `
        <div class="start-container">
            <div
                class="start-header"
                (click)="toggleMessage()"
            >
                <div class="play-arrow">
                    @if (hasInputs()) {
                        <app-svg-icon
                            [icon]="isMessageExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                            size="1.1rem"
                        />
                    }
                </div>
                <div class="icon-container">
                    <app-svg-icon
                        icon="flag"
                        size="1.25rem"
                    />
                </div>
                <h3>
                    <span class="node-name">{{ message.name }}</span> started
                </h3>
            </div>

            <!-- Collapsible Content -->
            <div
                class="collapsible-content grid-collapsible"
                [class.expanded]="isMessageExpanded"
            >
                <div class="start-content">
                    <!-- Input Parameters Section -->
                    @if (hasInputs()) {
                        <div class="input-container">
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
                                class="collapsible-content grid-collapsible"
                                [class.expanded]="isInputsExpanded"
                            >
                                <div class="collapsible-inner">
                                    <div class="input-content">
                                        <app-copy-button [text]="startInputJson" />
                                        <app-json-viewer
                                            [json]="getStartInput()"
                                            [expanded]="false"
                                        ></app-json-viewer>
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
            .start-container {
                position: relative;
                background-color: var(--color-nodes-background);
                border-radius: 8px;
                padding: var(--message-padding, 0.5rem 1rem);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border-left: 4px solid #d29922;
            }

            .start-header {
                display: flex;
                align-items: center;
                cursor: pointer;
                user-select: none;
            }

            .play-arrow {
                width: 1.1rem;
                margin-right: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;

                app-svg-icon {
                    color: #d29922;
                }
            }

            .icon-container {
                width: 28px;
                height: 28px;
                border-radius: 50%;
                background-color: #d29922;
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
            }

            .node-name {
                color: #d29922;
                font-weight: 400;
            }

            /* Collapsible content container */
            .collapsible-content {
                overflow: hidden;
                position: relative;
            }

            .start-content {
                display: flex;
                flex-direction: column;
                gap: 1rem;
                padding-left: 4.5rem;
            }

            .start-content > :first-child {
                margin-top: 1.25rem;
            }

            /* Section styling */
            .section-heading {
                font-size: var(--text-body-medium-size);
                font-weight: var(--text-body-medium-weight);
                line-height: var(--text-body-medium-line-height);
                color: var(--gray-300);
                margin-bottom: 0.5rem;
                cursor: pointer;
                user-select: none;
                display: flex;
                align-items: center;
            }

            .section-heading app-svg-icon {
                margin-right: 8px;
                color: #d29922;
                margin-left: -3px;
            }

            .input-container {
                margin-bottom: 0.5rem;
            }

            .input-content {
                position: relative;
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                padding: 1rem;
                overflow: auto;
                max-height: 400px;
                margin-left: 23px;

                &:hover app-copy-button {
                    opacity: 1;
                }
            }
        `,
    ],
})
export class StartMessageComponent {
    @Input() message!: GraphMessage;
    isMessageExpanded = false;
    isInputsExpanded = true;

    toggleMessage(): void {
        if (!this.hasInputs()) return;
        this.isMessageExpanded = !this.isMessageExpanded;
    }

    toggleInputs(event: Event): void {
        // Stop the click event from propagating to parent elements
        event.stopPropagation();
        this.isInputsExpanded = !this.isInputsExpanded;
    }

    hasInputs(): boolean {
        const input = this.getStartInput();
        return input && Object.keys(input).length > 0;
    }

    get startInputJson(): string {
        return JSON.stringify(this.getStartInput(), null, 2);
    }

    getStartInput(): Record<string, unknown> {
        if (!this.message.message_data) return {};

        if (this.message.message_data.message_type === MessageType.START && 'input' in this.message.message_data) {
            return this.message.message_data.input;
        }

        return {};
    }
}
