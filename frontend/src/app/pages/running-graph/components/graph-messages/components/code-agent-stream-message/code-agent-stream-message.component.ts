import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges, OnInit, SimpleChanges } from '@angular/core';
import { MarkdownModule } from 'ngx-markdown';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import {
    CodeAgentStreamMessageData,
    CodeAgentToolCall,
    GraphMessage,
    MessageType,
} from '../../../../models/graph-session-message.model';

interface ThinkingStep {
    text: string;
    toolCalls: CodeAgentToolCall[];
    timestamp: string;
}

@Component({
    selector: 'app-code-agent-stream-message',
    standalone: true,
    imports: [CommonModule, MarkdownModule, AppSvgIconComponent, CopyButtonComponent],
    animations: [expandCollapseAnimation],
    template: `
        <div
            class="code-agent-container"
            [class.in-progress]="!isFinal()"
        >
            <!-- Header -->
            <div
                class="code-agent-header"
                (click)="toggleMessage()"
            >
                <div class="play-arrow">
                    <app-svg-icon
                        [icon]="isExpanded ? 'caret-down-filled' : 'caret-right-filled'"
                        size="1rem"
                    />
                </div>
                <div
                    class="icon-container"
                    [class.working]="!isFinal()"
                >
                    <app-svg-icon
                        [icon]="isFinal() ? 'terminal-2' : 'loader'"
                        size="1rem"
                    />
                </div>
                <div class="header-text">
                    <span class="node-name">{{ message.name }}</span>
                    <span
                        class="status-badge"
                        *ngIf="!isFinal()"
                        >working...</span
                    >
                    <span
                        class="step-count"
                        *ngIf="thinkingSteps.length > 0"
                    >
                        {{ thinkingSteps.length }} step{{ thinkingSteps.length !== 1 ? 's' : '' }}
                    </span>
                </div>
            </div>

            <!-- Steps (at the top, always visible when expanded) -->
            <div
                class="collapsible-content"
                [@expandCollapse]="isExpanded ? 'expanded' : 'collapsed'"
            >
                <div
                    class="steps-container"
                    *ngIf="thinkingSteps.length > 0"
                >
                    <div
                        class="step-item"
                        *ngFor="let step of thinkingSteps; let i = index"
                    >
                        <div
                            class="step-header"
                            (click)="toggleStep(i)"
                        >
                            <app-svg-icon
                                [icon]="expandedSteps[i] ? 'caret-down-filled' : 'caret-right-filled'"
                                size="1rem"
                            />
                            <span class="step-summary">{{ getStepSummary(step, i) }}</span>
                        </div>

                        <div
                            class="collapsible-content"
                            [@expandCollapse]="expandedSteps[i] ? 'expanded' : 'collapsed'"
                        >
                            <div class="step-content">
                                <div
                                    class="tool-call-item"
                                    *ngFor="let tc of step.toolCalls"
                                >
                                    <div class="tool-call-name">
                                        <app-svg-icon
                                            icon="tool"
                                            size="1rem"
                                        />
                                        {{ tc.name }}
                                    </div>
                                    <div
                                        class="tool-call-input"
                                        *ngIf="tc.input"
                                    >
                                        {{ truncate(tc.input, 200) }}
                                    </div>
                                    <div
                                        class="tool-call-output"
                                        *ngIf="tc.output"
                                    >
                                        {{ truncate(tc.output, 300) }}
                                    </div>
                                </div>

                                <div
                                    class="thinking-text"
                                    *ngIf="step.text"
                                >
                                    {{ truncate(step.text, 2000) }}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Final result (below steps) -->
            <div
                class="final-result"
                *ngIf="getText()"
            >
                <app-copy-button [text]="getText()" />
                <markdown
                    [data]="getText()"
                    class="markdown-content"
                ></markdown>
            </div>
        </div>
    `,
    styles: `
        :host {
            display: flex;
            flex-direction: column;
        }

        .code-agent-container {
            background-color: var(--color-nodes-background);
            border-radius: var(--radius-lg);
            padding: var(--message-padding, var(--space-xl));
            box-shadow: 0 4px 12px var(--black-alpha-15);
            border-left: 4px solid #2dd4bf;
        }

        .code-agent-header {
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
                color: #2dd4bf;
            }
        }

        .icon-container {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background-color: #2dd4bf;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: var(--space-xl);
            flex-shrink: 0;

            app-svg-icon {
                color: var(--gray-900);
            }
        }

        .header-text {
            flex: 1;
            display: flex;
            align-items: center;
            gap: var(--space-md);
        }

        .node-name {
            color: var(--color-text-primary);
            font-size: var(--font-size-xl);
            font-weight: var(--font-weight-semibold);
        }

        .step-count {
            color: var(--color-text-secondary);
            font-size: var(--font-size-md);
        }

        .status-badge {
            color: #fbbf24;
            font-size: var(--font-size-sm);
            font-weight: var(--font-weight-medium);
        }

        .code-agent-container.in-progress {
            border-left-color: #fbbf24;
        }

        .icon-container.working {
            background-color: #fbbf24;
        }

        .icon-container.working app-svg-icon {
            animation: spin 1.5s linear infinite;
        }

        @keyframes spin {
            from {
                transform: rotate(0deg);
            }
            to {
                transform: rotate(360deg);
            }
        }

        .final-result {
            position: relative;
            padding: var(--space-lg) var(--space-lg) 0 5.5rem;
            color: var(--color-text-primary);
            max-height: 400px;
            overflow-y: auto;

            &:hover app-copy-button {
                opacity: 1;
            }
        }

        .collapsible-content {
            overflow: hidden;
            position: relative;

            &.ng-animating {
                overflow: hidden;
            }
        }

        .steps-container {
            display: flex;
            flex-direction: column;
            gap: var(--space-2xs);
            padding: var(--space-md) 0 0 5.5rem;
            border-top: 1px solid var(--gray-750);
            margin-top: var(--space-md);
        }

        .step-item {
            border-radius: var(--radius-md);
        }

        .step-header {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            cursor: pointer;
            user-select: none;
            padding: var(--space-xs) var(--space-sm);
            border-radius: var(--radius-sm);

            &:hover {
                background-color: var(--gray-800);
            }

            app-svg-icon {
                color: #2dd4bf;
            }
        }

        .step-label {
            color: var(--color-text-secondary);
            font-size: var(--font-size-md);
            font-weight: var(--font-weight-medium);
        }

        .step-tools {
            color: var(--color-text-tertiary);
            font-size: var(--font-size-sm);
            display: flex;
            align-items: center;
            gap: var(--space-2xs);

            app-svg-icon {
                color: var(--color-text-tertiary);
            }
        }

        .step-content {
            display: flex;
            flex-direction: column;
            gap: var(--space-sm);
            padding: var(--space-sm) 0 var(--space-sm) var(--space-2xl);
        }

        .tool-call-item {
            background-color: var(--gray-800);
            border: 1px solid var(--gray-750);
            border-radius: var(--radius-md);
            padding: var(--space-sm) var(--space-md);
        }

        .tool-call-name {
            color: #2dd4bf;
            font-weight: var(--font-weight-semibold);
            font-size: var(--font-size-md);
            display: flex;
            align-items: center;
            gap: var(--space-xs);
        }

        .tool-call-input {
            color: var(--color-text-secondary);
            font-size: var(--font-size-xs);
            margin-top: var(--space-2xs);
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 80px;
            overflow-y: auto;
        }

        .tool-call-output {
            color: var(--color-text-tertiary);
            font-size: var(--font-size-xs);
            margin-top: var(--space-2xs);
            padding-top: var(--space-2xs);
            border-top: 1px solid var(--gray-750);
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 120px;
            overflow-y: auto;
        }

        .thinking-text {
            color: var(--color-text-secondary);
            font-size: var(--font-size-sm);
            font-style: italic;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 300px;
            overflow-y: auto;
        }

        .markdown-content {
            ::ng-deep {
                p {
                    margin: 0.4em 0;
                }
                code {
                    background-color: var(--gray-800);
                    padding: 0.15em 0.4em;
                    border-radius: var(--radius-sm);
                    font-size: 0.85em;
                }
                pre {
                    background-color: var(--gray-850);
                    border: 1px solid var(--gray-750);
                    border-radius: var(--radius-md);
                    padding: var(--space-md);
                    overflow-x: auto;
                }
            }
        }
    `,
})
export class CodeAgentStreamMessageComponent implements OnInit, OnChanges {
    @Input() public message!: GraphMessage;
    @Input() public allMessages: GraphMessage[] = [];

    public isExpanded = false;
    public expandedSteps: boolean[] = [];
    public thinkingSteps: ThinkingStep[] = [];
    public totalToolCalls = 0;

    public ngOnInit(): void {
        this.buildThinkingSteps();
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['message'] || changes['allMessages']) {
            this.buildThinkingSteps();
        }
    }

    public toggleMessage(): void {
        this.isExpanded = !this.isExpanded;
    }

    public toggleStep(index: number): void {
        this.expandedSteps[index] = !this.expandedSteps[index];
    }

    public isFinal(): boolean {
        return this.getData()?.is_final === true;
    }

    public getText(): string {
        return this.getData()?.text || '';
    }

    public getStepSummary(step: ThinkingStep, index: number): string {
        // Extract a meaningful label from thinking text
        const label = this.extractThinkingLabel(step.text);

        // Group tool calls by name to avoid "Running command, Running command, ..."
        const toolCounts = new Map<string, { count: number; detail: string }>();
        for (const tc of step.toolCalls) {
            const detail = this.extractToolDetail(tc);
            const existing = toolCounts.get(tc.name);
            if (existing) {
                existing.count++;
            } else {
                toolCounts.set(tc.name, { count: 1, detail });
            }
        }
        const tools: string[] = [];
        for (const [name, info] of toolCounts) {
            if (info.count > 1) {
                tools.push(`${name} (${info.count}x)`);
            } else {
                tools.push(info.detail ? `${name} ${info.detail}` : name);
            }
        }
        const toolStr = tools.join(', ');

        if (label && toolStr) {
            return `${label}  ·  ${toolStr}`;
        }
        return label || toolStr || `Step ${index + 1}`;
    }

    private extractThinkingLabel(text: string): string {
        if (!text) return '';
        // Try to extract **bold heading** first
        const boldMatch = text.match(/\*\*([^*]+)\*\*/);
        if (boldMatch) {
            return boldMatch[1].trim();
        }
        // Fall back to first sentence or line
        const firstLine = text.split('\n')[0].trim();
        const firstSentence = firstLine.split(/[.!?]/)[0].trim();
        if (firstSentence.length > 0 && firstSentence.length <= 80) {
            return firstSentence;
        }
        return firstLine.substring(0, 80) + (firstLine.length > 80 ? '...' : '');
    }

    public truncate(str: string, max: number): string {
        return str.length > max ? str.substring(0, max) + '...' : str;
    }

    private extractToolDetail(tc: CodeAgentToolCall): string {
        if (!tc.input) return '';
        try {
            const parsed = JSON.parse(tc.input);
            // Extract file path for read/write/apply_patch
            if (parsed.filePath) {
                const parts = parsed.filePath.split('/');
                return parts.slice(-2).join('/');
            }
            if (parsed.path && parsed.pattern) {
                return `${parsed.pattern}`;
            }
            if (parsed.command) {
                return this.truncate(parsed.command, 40);
            }
            if (parsed.patchText) {
                // Extract target file from patch text
                const fileMatch = parsed.patchText.match(/(?:Update|Add|Delete) File:\s*(\S+)/);
                if (fileMatch) {
                    const parts = fileMatch[1].split('/');
                    return parts.slice(-2).join('/');
                }
                return '(patch)';
            }
        } catch {
            // Not JSON, try to extract something useful
            if (tc.input.length < 50) return tc.input;
        }
        return '';
    }

    private buildThinkingSteps(): void {
        if (!this.allMessages || !this.message) return;

        const nodeName = this.message.name;

        // Collect non-final code_agent_stream messages for this node,
        // consolidating by step_id (same step_id → update in-place).
        const stepMap = new Map<number | string, ThinkingStep>();
        const stepOrder: (number | string)[] = [];
        let fallbackKey = 0;

        for (const msg of this.allMessages) {
            if (!msg.message_data) continue;
            if (msg.message_data.message_type !== 'code_agent_stream') continue;
            if (msg.name !== nodeName) continue;

            const data = msg.message_data as CodeAgentStreamMessageData;
            if (data.is_final) continue;

            const key = data.step_id != null ? data.step_id : `_fb_${fallbackKey++}`;
            const existing = stepMap.get(key);

            if (existing) {
                // Same step_id — replace text (latest wins), merge tool calls
                existing.text = data.text || existing.text;
                if (data.tool_calls?.length) {
                    existing.toolCalls = data.tool_calls;
                }
                existing.timestamp = msg.created_at;
            } else {
                stepMap.set(key, {
                    text: data.text || '',
                    toolCalls: data.tool_calls || [],
                    timestamp: msg.created_at,
                });
                stepOrder.push(key);
            }
        }

        const steps = stepOrder.map((k) => stepMap.get(k)!);

        // Preserve existing expanded state for steps that haven't changed
        const oldLength = this.expandedSteps.length;
        this.thinkingSteps = steps;
        if (steps.length > oldLength) {
            this.expandedSteps = [...this.expandedSteps, ...new Array(steps.length - oldLength).fill(false)];
        }
        this.totalToolCalls = steps.reduce((sum, s) => sum + s.toolCalls.length, 0);
    }

    private getData(): CodeAgentStreamMessageData | null {
        if (this.message.message_data && this.message.message_data.message_type === MessageType.CODE_AGENT_STREAM) {
            return this.message.message_data as CodeAgentStreamMessageData;
        }
        return null;
    }
}
