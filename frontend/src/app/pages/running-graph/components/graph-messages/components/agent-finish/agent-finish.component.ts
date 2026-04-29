import { CommonModule } from '@angular/common';
import { Component, Input, OnInit } from '@angular/core';
import { NgxJsonViewerModule } from 'ngx-json-viewer';
import { MarkdownModule } from 'ngx-markdown';

import { GetAgentRequest } from '../../../../../../features/staff/models/agent.model';
import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { AgentFinishMessageData, GraphMessage, MessageType } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-agent-finish-message',
    standalone: true,
    imports: [CommonModule, MarkdownModule, NgxJsonViewerModule, AppSvgIconComponent],
    animations: [expandCollapseAnimation],
    template: `
        <div class="agent-flow-container">
            <!-- Agent Message Header with Toggle -->
            <div
                class="agent-header"
                (click)="toggleMessage()"
            >
                <div class="play-arrow">
                    <app-svg-icon
                        [icon]="isMessageExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                        size="1.1rem"
                    />
                </div>
                <div class="icon-container">
                    <app-svg-icon
                        icon="robot"
                        size="1.25rem"
                    />
                </div>
                <h3>
                    Agent <span class="agent-name">{{ getAgentName() }}</span> finished doing the assigned task.
                </h3>
            </div>

            <!-- Collapsible Agent Content - Thought Section Only -->
            <div
                class="collapsible-content"
                [@expandCollapse]="isMessageExpanded ? 'expanded' : 'collapsed'"
            >
                <div class="agent-content">
                    <!-- Thought Section -->
                    <div
                        class="thought-container"
                        *ngIf="agentFinishMessageData?.thought"
                    >
                        <div
                            class="section-heading"
                            (click)="toggleSection('thought')"
                        >
                            <app-svg-icon
                                [icon]="isThoughtExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                                size="1.1rem"
                            />
                            Thought
                        </div>
                        <div
                            class="collapsible-content"
                            [@expandCollapse]="isThoughtExpanded ? 'expanded' : 'collapsed'"
                        >
                            <div class="thought-bubble">
                                <span class="thought-quote">"</span>{{ cleanThought(agentFinishMessageData?.thought)
                                }}<span class="thought-quote">"</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Task Result as Separate Message Bubble -->
        <div
            class="result-message-container"
            *ngIf="agentFinishMessageData?.output"
        >
            <div class="result-content">
                <ngx-json-viewer
                    *ngIf="isValidJson(agentFinishMessageData?.output)"
                    [json]="getParsedJson(agentFinishMessageData?.output)"
                    [expanded]="true"
                ></ngx-json-viewer>
                <markdown
                    *ngIf="!isValidJson(agentFinishMessageData?.output)"
                    [data]="cleanOutput(agentFinishMessageData?.output)"
                    class="markdown-content"
                >
                </markdown>
            </div>
        </div>
    `,
    styles: [
        `
            :host {
                display: flex;
                flex-direction: column;
                gap: 1rem;
            }

            .agent-flow-container {
                background-color: var(--color-nodes-background);
                border-radius: 8px;
                padding: var(--message-padding, 1.25rem);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                border-left: 4px solid #8e5cd9;
            }

            .agent-header {
                display: flex;
                align-items: center;
                cursor: pointer;
                user-select: none;
            }

            .play-arrow {
                margin-top: 2px;
                margin-right: 16px;
                display: flex;
                align-items: center;

                app-svg-icon {
                    color: #8e5cd9;
                }
            }

            .icon-container {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background-color: #8e5cd9;
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

            .agent-name {
                color: #8e5cd9;
                font-weight: 400;
                margin-right: 5px;
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
                color: #8e5cd9;
                margin-left: -3px;
            }

            .thought-bubble {
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                padding: 1rem;
                position: relative;
                color: var(--gray-200);
                font-style: italic;
                margin-left: 23px;
            }

            .thought-quote {
                color: #8e5cd9;
                font-size: 1.5rem;
                font-weight: bold;
                vertical-align: sub;
                line-height: 0;
            }

            /* Task Result Styling - Message Bubble */
            .result-message-container {
                max-width: 85%;
                position: relative;
            }

            .result-content {
                background-color: var(--gray-850);
                border-radius: 18px;
                border-top-left-radius: 4px;
                padding: 1rem;
                color: white;
                word-break: break-word;
                overflow-y: auto;
                transition: max-height 0.3s ease;
                box-shadow: 0 4px 12px rgba(14, 14, 14, 0.25);
                position: relative;
            }
        `,
    ],
})
export class AgentFinishMessageComponent implements OnInit {
    @Input() message!: GraphMessage;
    @Input() agent: GetAgentRequest | null = null;

    isMessageExpanded = false;
    isThoughtExpanded = true;
    isCollapsed = true;
    private outputJsonData: unknown = null;

    ngOnInit() {
        // Any initialization logic here
    }

    toggleMessage(): void {
        this.isMessageExpanded = !this.isMessageExpanded;
    }

    hasThought(): boolean {
        return !!this.agentFinishMessageData?.thought && this.agentFinishMessageData.thought.trim() !== '';
    }

    toggleSection(section: 'thought' | 'output'): void {
        if (section === 'thought') {
            this.isThoughtExpanded = !this.isThoughtExpanded;
        }
    }

    toggleCollapse(): void {
        this.isCollapsed = !this.isCollapsed;

        // Toggle max-height dynamically based on collapsed state
        const resultContent = document.querySelector('.result-content') as HTMLElement;
        if (resultContent) {
            resultContent.style.maxHeight = this.isCollapsed ? '300px' : 'none';
            resultContent.style.overflow = this.isCollapsed ? 'hidden' : 'auto';
        }
    }

    shouldShowToggle(): boolean {
        if (!this.agentFinishMessageData?.output) return false;
        const output = this.agentFinishMessageData.output;
        // Show toggle button if content is longer than approximately 5 lines
        return output.split('\n').length > 5 || output.length > 500;
    }

    cleanThought(thought: string | undefined): string {
        if (!thought) return '';
        return thought
            .replace(/```[\s\S]*?```/g, '')
            .replace(/^```/, '')
            .replace(/```$/, '')
            .replace(/^Thought: /g, '')
            .replace(/Thought: /g, '')
            .trim();
    }

    cleanOutput(output: string | undefined): string {
        if (!output) return '';
        return output
            .replace(/```[\s\S]*?```/g, '')
            .replace(/^```/, '')
            .replace(/```$/, '')
            .replace(/^Output: /g, '')
            .replace(/Output: /g, '')
            .trim();
    }

    get agentFinishMessageData(): AgentFinishMessageData | null {
        if (this.message.message_data && this.message.message_data.message_type === MessageType.AGENT_FINISH) {
            return this.message.message_data as AgentFinishMessageData;
        }
        return null;
    }

    getAgentName(): string {
        if (this.agent && this.agent.role) {
            // Limit agent name to 50 characters
            const name = this.agent.role;
            return name.length > 50 ? name.substring(0, 50) + '...' : name;
        }
        return 'Unknown';
    }

    isValidJson(str: string | undefined): boolean {
        if (!str) return false;
        try {
            JSON.parse(str);
            return true;
        } catch {
            return false;
        }
    }

    getParsedJson(str: string | undefined): unknown {
        if (!str) return null;
        if (this.outputJsonData === null) {
            try {
                this.outputJsonData = JSON.parse(str);
            } catch {
                this.outputJsonData = null;
            }
        }
        return this.outputJsonData;
    }
}
