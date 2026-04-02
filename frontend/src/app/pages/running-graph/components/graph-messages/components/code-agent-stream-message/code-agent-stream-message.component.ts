import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges, OnInit, SimpleChanges } from '@angular/core';
import { MarkdownModule } from 'ngx-markdown';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
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
    imports: [CommonModule, MarkdownModule],
    animations: [expandCollapseAnimation],
    template: `
        <div class="code-agent-container" [class.in-progress]="!isFinal()">
            <!-- Header -->
            <div class="code-agent-header" (click)="toggleMessage()">
                <div class="play-arrow">
                    <i class="ti" [ngClass]="isExpanded ? 'ti-caret-down-filled' : 'ti-caret-right-filled'"></i>
                </div>
                <div class="icon-container" [class.working]="!isFinal()">
                    <i class="ti" [ngClass]="isFinal() ? 'ti-terminal-2' : 'ti-loader'"></i>
                </div>
                <div class="header-text">
                    <span class="node-name">{{ message.name }}</span>
                    <span class="status-badge" *ngIf="!isFinal()">working...</span>
                    <span class="step-count" *ngIf="thinkingSteps.length > 0">
                        {{ thinkingSteps.length }} step{{ thinkingSteps.length !== 1 ? 's' : '' }}
                    </span>
                </div>
            </div>

            <!-- Steps (at the top, always visible when expanded) -->
            <div class="collapsible-content" [@expandCollapse]="isExpanded ? 'expanded' : 'collapsed'">
                <div class="steps-container" *ngIf="thinkingSteps.length > 0">
                    <div class="step-item" *ngFor="let step of thinkingSteps; let i = index">
                        <div class="step-header" (click)="toggleStep(i)">
                            <i
                                class="ti"
                                [ngClass]="expandedSteps[i] ? 'ti-caret-down-filled' : 'ti-caret-right-filled'"
                            ></i>
                            <span class="step-summary">{{ getStepSummary(step, i) }}</span>
                        </div>

                        <div
                            class="collapsible-content"
                            [@expandCollapse]="expandedSteps[i] ? 'expanded' : 'collapsed'"
                        >
                            <div class="step-content">
                                <div class="tool-call-item" *ngFor="let tc of step.toolCalls">
                                    <div class="tool-call-name">
                                        <i class="ti ti-tool"></i>
                                        {{ tc.name }}
                                    </div>
                                    <div class="tool-call-input" *ngIf="tc.input">
                                        {{ truncate(tc.input, 200) }}
                                    </div>
                                    <div class="tool-call-output" *ngIf="tc.output">
                                        {{ truncate(tc.output, 300) }}
                                    </div>
                                </div>

                                <div class="thinking-text" *ngIf="step.text">
                                    {{ truncate(step.text, 2000) }}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Final result (below steps) -->
            <div class="final-result" *ngIf="getText()">
                <markdown [data]="getText()" class="markdown-content"></markdown>
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
            border-radius: 8px;
            padding: 1.25rem;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            border-left: 4px solid #2dd4bf;
        }

        .code-agent-header {
            display: flex;
            align-items: center;
            cursor: pointer;
            user-select: none;
        }

        .play-arrow {
            margin-right: 16px;
            display: flex;
            align-items: center;

            i {
                color: #2dd4bf;
                font-size: 1.1rem;
                transition: transform 0.3s ease;
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
            margin-right: 20px;
            flex-shrink: 0;

            i {
                color: var(--gray-900);
                font-size: 1.25rem;
            }
        }

        .header-text {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .node-name {
            color: var(--gray-100);
            font-size: 1.1rem;
            font-weight: 600;
        }

        .step-count {
            color: var(--gray-400);
            font-size: 0.85rem;
        }

        .status-badge {
            color: #fbbf24;
            font-size: 0.8rem;
            font-weight: 500;
        }

        .code-agent-container.in-progress {
            border-left-color: #fbbf24;
        }

        .icon-container.working {
            background-color: #fbbf24;
        }

        .icon-container.working i {
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
            padding: 1rem 1rem 0 5.5rem;
            color: var(--gray-200);
            max-height: 400px;
            overflow-y: auto;
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
            gap: 0.25rem;
            padding: 0.75rem 0 0 5.5rem;
            border-top: 1px solid var(--gray-750);
            margin-top: 0.75rem;
        }

        .step-item {
            border-radius: 6px;
        }

        .step-header {
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            user-select: none;
            padding: 0.35rem 0.5rem;
            border-radius: 4px;

            &:hover {
                background-color: var(--gray-800);
            }

            i {
                color: #2dd4bf;
                font-size: 0.9rem;
            }
        }

        .step-label {
            color: var(--gray-300);
            font-size: 0.85rem;
            font-weight: 500;
        }

        .step-tools {
            color: var(--gray-500);
            font-size: 0.8rem;
            display: flex;
            align-items: center;
            gap: 4px;

            i {
                font-size: 0.75rem;
                color: var(--gray-500);
            }
        }

        .step-content {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            padding: 0.5rem 0 0.5rem 1.5rem;
        }

        .tool-call-item {
            background-color: var(--gray-800);
            border: 1px solid var(--gray-750);
            border-radius: 6px;
            padding: 0.6rem 0.75rem;
        }

        .tool-call-name {
            color: #2dd4bf;
            font-weight: 600;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;

            i {
                font-size: 0.8rem;
            }
        }

        .tool-call-input {
            color: var(--gray-400);
            font-size: 0.78rem;
            margin-top: 3px;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 80px;
            overflow-y: auto;
        }

        .tool-call-output {
            color: var(--gray-500);
            font-size: 0.75rem;
            margin-top: 4px;
            padding-top: 4px;
            border-top: 1px solid var(--gray-750);
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 120px;
            overflow-y: auto;
        }

        .thinking-text {
            color: var(--gray-400);
            font-size: 0.82rem;
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
                    border-radius: 3px;
                    font-size: 0.85em;
                }
                pre {
                    background-color: var(--gray-850);
                    border: 1px solid var(--gray-750);
                    border-radius: 6px;
                    padding: 0.75rem;
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
