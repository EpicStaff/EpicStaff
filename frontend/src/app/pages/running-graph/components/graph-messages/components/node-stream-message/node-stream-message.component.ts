import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import {
    AgentNodeStreamMessageData,
    GraphMessage,
    MessageType,
    NodeStreamTaskFinishData,
    NodeStreamToolCallData,
    NodeStreamToolResultData,
    TaskNodeStreamMessageData,
} from '../../../../models/graph-session-message.model';

type NodeStreamMessageData = TaskNodeStreamMessageData | AgentNodeStreamMessageData;
type NodeStreamType = MessageType.TASK_NODE_STREAM | MessageType.AGENT_NODE_STREAM;

interface NodeStreamToolStep {
    key: string;
    call: NodeStreamToolCallData | null;
    result: NodeStreamToolResultData | null;
}

interface NodeStreamTaskGroup {
    key: string;
    taskName: string | null;
    order: number;
    toolSteps: NodeStreamToolStep[];
    message: string | null;
    stopReason: string | null;
    iterations: number | null;
    toolInvocations: number | null;
    tokenUsage: Record<string, number> | null;
}

// Icon/color per node type, matching the conventions already used by the sibling
// app-task-message ('list-check' / #30a46c) and app-agent-message ('robot' / #8e5cd9) cards.
const NODE_TYPE_STYLE: Record<NodeStreamType, { icon: string; color: string }> = {
    [MessageType.TASK_NODE_STREAM]: { icon: 'list-check', color: '#30a46c' },
    [MessageType.AGENT_NODE_STREAM]: { icon: 'robot', color: '#8e5cd9' },
};

@Component({
    selector: 'app-node-stream-message',
    imports: [AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div
            class="node-stream-container"
            [class.in-progress]="!isDone()"
            [style.--stream-color]="color()"
        >
            <!-- Header -->
            <div
                class="node-stream-header"
                (click)="toggleMessage()"
            >
                <div class="play-arrow">
                    <app-svg-icon
                        [icon]="isExpanded() ? 'caret-down-filled' : 'caret-right-filled'"
                        size="1rem"
                    />
                </div>
                <div
                    class="icon-container"
                    [class.working]="!isDone()"
                >
                    <app-svg-icon
                        [icon]="isDone() ? icon() : 'loader'"
                        size="1rem"
                    />
                </div>
                <div class="header-text">
                    <span class="node-name">{{ message().name }}</span>
                    @if (!isDone()) {
                        <span class="status-badge">working...</span>
                    }
                    @if (hasContent()) {
                        <span class="step-count">
                            @if (namedTaskCount() > 0) {
                                {{ namedTaskCount() }} task{{ namedTaskCount() !== 1 ? 's' : '' }}
                            } @else {
                                {{ stepCount() }} step{{ stepCount() !== 1 ? 's' : '' }}
                            }
                        </span>
                    }
                </div>
            </div>

            <!-- Steps -->
            <div
                class="collapsible-content"
                [class.expanded]="isExpanded()"
            >
                <div class="collapsible-inner">
                    @if (hasContent()) {
                        <div class="task-groups">
                            @for (group of taskGroups(); track group.key) {
                                <div class="task-group">
                                    @if (group.taskName) {
                                        <div class="task-group-header">
                                            <app-svg-icon
                                                icon="list-check"
                                                size="0.85rem"
                                            />
                                            {{ group.taskName }}
                                        </div>
                                    }
                                    <div class="steps-container">
                                        @for (step of group.toolSteps; track step.key) {
                                            <div class="step-item">
                                                <div
                                                    class="step-header"
                                                    (click)="toggleStep(step)"
                                                >
                                                    <app-svg-icon
                                                        [icon]="
                                                            isStepExpanded(step)
                                                                ? 'caret-down-filled'
                                                                : 'caret-right-filled'
                                                        "
                                                        size="1rem"
                                                    />
                                                    <app-svg-icon
                                                        [icon]="isStepError(step) ? 'alert-circle' : 'tool'"
                                                        size="0.9rem"
                                                        class="step-icon"
                                                        [class.is-error]="isStepError(step)"
                                                    />
                                                    <span class="step-summary">{{ getStepSummary(step) }}</span>
                                                </div>

                                                <div
                                                    class="collapsible-content"
                                                    [class.expanded]="isStepExpanded(step)"
                                                >
                                                    <div class="collapsible-inner">
                                                        <div class="step-content">
                                                            @if (step.call; as call) {
                                                                <div class="tool-call-item">
                                                                    <div class="tool-call-label">Arguments</div>
                                                                    <div class="tool-call-input">
                                                                        {{ truncate(call.arguments, 400) }}
                                                                    </div>
                                                                    @if (call.truncated) {
                                                                        <div class="truncated-hint">truncated</div>
                                                                    }
                                                                </div>
                                                            }

                                                            @if (step.result; as result) {
                                                                <div
                                                                    class="tool-result-item"
                                                                    [class.is-error]="result.is_error"
                                                                >
                                                                    <div class="tool-call-label">
                                                                        {{ result.is_error ? 'Error' : 'Result' }}
                                                                    </div>
                                                                    <div class="tool-call-output">
                                                                        {{ truncate(result.content, 600) }}
                                                                    </div>
                                                                    @if (result.truncated) {
                                                                        <div class="truncated-hint">truncated</div>
                                                                    }
                                                                </div>
                                                            }
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        }
                                    </div>

                                    @if (group.message; as taskMessage) {
                                        <div class="task-output">
                                            <div class="tool-call-label">Output</div>
                                            <div class="task-output-text">{{ taskMessage }}</div>
                                        </div>
                                    }

                                    @if (group.tokenUsage; as tokenUsage) {
                                        <div class="token-usage">
                                            Tokens:
                                            @if (tokenUsage['total_tokens'] !== undefined) {
                                                {{ tokenUsage['total_tokens'] }} total
                                            }
                                            @if (tokenUsage['prompt_tokens'] !== undefined) {
                                                · {{ tokenUsage['prompt_tokens'] }} prompt
                                            }
                                            @if (tokenUsage['completion_tokens'] !== undefined) {
                                                · {{ tokenUsage['completion_tokens'] }} completion
                                            }
                                        </div>
                                    }
                                </div>
                            }
                        </div>
                    }
                </div>
            </div>
        </div>
    `,
    styles: `
        :host {
            display: flex;
            flex-direction: column;
        }

        .node-stream-container {
            background-color: var(--color-nodes-background);
            border-radius: 8px;
            padding: var(--message-padding, 1.25rem);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            border-left: 4px solid var(--stream-color, #2dd4bf);
        }

        .node-stream-header {
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
                color: var(--stream-color);
            }
        }

        .icon-container {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background-color: var(--stream-color);
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 20px;
            flex-shrink: 0;

            app-svg-icon {
                color: var(--gray-900);
            }
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

        .status-badge {
            color: #fbbf24;
            font-size: 0.8rem;
            font-weight: 500;
        }

        .step-count {
            color: var(--gray-400);
            font-size: 0.85rem;
        }

        .node-stream-container.in-progress {
            border-left-color: #fbbf24;
        }

        .collapsible-content {
            display: grid;
            grid-template-rows: 0fr;
            opacity: 0;
            visibility: hidden;
            transition:
                grid-template-rows 180ms ease-in-out,
                opacity 180ms ease-in-out,
                visibility 180ms ease-in-out;

            &.expanded {
                grid-template-rows: 1fr;
                opacity: 1;
                visibility: visible;
            }
        }

        .collapsible-inner {
            min-height: 0;
            overflow: hidden;
        }

        .task-groups {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
            padding: 0.75rem 0 0 5.5rem;
            border-top: 1px solid var(--gray-750);
            margin-top: 0.75rem;
        }

        .task-group-header {
            display: flex;
            align-items: center;
            gap: 6px;
            color: var(--stream-color);
            font-size: 0.85rem;
            font-weight: 600;
            margin-bottom: 0.35rem;
        }

        .steps-container {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
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

            app-svg-icon {
                color: var(--stream-color);
            }

            .step-icon.is-error {
                color: #ff6b6b;
            }
        }

        .step-summary {
            color: var(--gray-300);
            font-size: 0.85rem;
            font-weight: 500;
        }

        .step-content {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            padding: 0.5rem 0 0.5rem 1.5rem;
        }

        .tool-call-item,
        .tool-result-item {
            background-color: var(--gray-800);
            border: 1px solid var(--gray-750);
            border-radius: 6px;
            padding: 0.6rem 0.75rem;
        }

        .tool-result-item.is-error {
            border-color: #ff6b6b;
        }

        .tool-call-label {
            color: var(--stream-color);
            font-weight: 600;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.02em;
        }

        .tool-call-input,
        .tool-call-output {
            color: var(--gray-400);
            font-size: 0.78rem;
            margin-top: 3px;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 160px;
            overflow-y: auto;
        }

        .tool-result-item.is-error .tool-call-output {
            color: #ff9a9a;
        }

        .truncated-hint {
            color: var(--gray-500);
            font-size: 0.7rem;
            font-style: italic;
            margin-top: 4px;
        }

        .task-output {
            background-color: var(--gray-800);
            border: 1px solid var(--gray-750);
            border-radius: 6px;
            padding: 0.6rem 0.75rem;
            margin-top: 0.5rem;
        }

        .task-output-text {
            color: var(--gray-300);
            font-size: 0.85rem;
            margin-top: 3px;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .token-usage {
            color: var(--gray-500);
            font-size: 0.75rem;
            margin-top: 0.4rem;
        }
    `,
})
export class NodeStreamMessageComponent {
    readonly message = input.required<GraphMessage>();
    readonly allMessages = input<GraphMessage[]>([]);
    // True once a `finish`/`error` message for this node has arrived, even when the shown
    // stream message's own `is_final` was never set (see GraphMessagesComponent.isNodeStreamCompleted).
    readonly nodeCompleted = input<boolean>(false);

    readonly isExpanded = signal(true);
    private readonly expandedStepKeys = signal<ReadonlySet<string>>(new Set());

    readonly nodeType = computed(() => this.message().message_data.message_type as NodeStreamType);
    readonly icon = computed(() => NODE_TYPE_STYLE[this.nodeType()].icon);
    readonly color = computed(() => NODE_TYPE_STYLE[this.nodeType()].color);

    readonly isFinal = computed(() => (this.message().message_data as NodeStreamMessageData).is_final === true);
    // Card is done when the stream message itself is final OR the node's finish/error
    // message has already arrived — drives the "working..." badge and spinning icon state.
    readonly isDone = computed(() => this.isFinal() || this.nodeCompleted());

    // Task-centric grouping: every task (task_start/task_finish) creates/keeps a group even
    // when it never makes a tool call, so tool-less tasks still render with their output
    // message. tool_call/tool_result events are paired by `tool_call_id === call.id`, NOT by
    // shared step_id (they don't share one). Agents/tasks without `data.task` (TaskNode,
    // single-task agents) collapse into one flat, header-less `__default__` group — same
    // behavior as before.
    readonly taskGroups = computed<NodeStreamTaskGroup[]>(() => {
        const message = this.message();
        const nodeName = message.name;
        const type = message.message_data.message_type;

        const groups = new Map<string, NodeStreamTaskGroup>();
        const groupOrder: string[] = [];

        for (const msg of this.allMessages()) {
            const data = msg.message_data;
            if (!data || data.message_type !== type || msg.name !== nodeName) continue;

            const streamData = data as NodeStreamMessageData;
            const task = streamData.data.task;
            const key = task ? `task_${task.order}_${task.name}` : '__default__';

            let group = groups.get(key);
            if (!group) {
                group = {
                    key,
                    taskName: task ? task.name : null,
                    order: task ? task.order : 0,
                    toolSteps: [],
                    message: null,
                    stopReason: null,
                    iterations: null,
                    toolInvocations: null,
                    tokenUsage: null,
                };
                groups.set(key, group);
                groupOrder.push(key);
            }

            if (streamData.event === 'tool_call') {
                const call = streamData.data as NodeStreamToolCallData;
                group.toolSteps.push({ key: `call_${call.id}`, call, result: null });
            } else if (streamData.event === 'tool_result') {
                const result = streamData.data as NodeStreamToolResultData;
                const step = group.toolSteps.find((s) => s.call?.id === result.tool_call_id);
                if (step) {
                    step.result = result;
                } else {
                    group.toolSteps.push({ key: `result_${result.tool_call_id}`, call: null, result });
                }
            } else if (streamData.event === 'task_finish') {
                const finish = streamData.data as NodeStreamTaskFinishData;
                group.message = finish.message;
                group.stopReason = finish.stop_reason ?? null;
                group.iterations = finish.iterations ?? null;
                group.toolInvocations = finish.tool_invocations ?? null;
                group.tokenUsage = finish.token_usage ?? null;
            }
            // event === 'task_start': the group lookup/creation above already ensures the
            // task shows up even when it never makes a tool call.
        }

        return groupOrder.map((key) => groups.get(key)!).sort((a, b) => a.order - b.order);
    });

    readonly hasContent = computed(() => this.taskGroups().length > 0);
    readonly stepCount = computed(() => this.taskGroups().reduce((sum, group) => sum + group.toolSteps.length, 0));
    readonly namedTaskCount = computed(() => this.taskGroups().filter((group) => group.taskName !== null).length);

    toggleMessage(): void {
        this.isExpanded.update((value) => !value);
    }

    isStepExpanded(step: NodeStreamToolStep): boolean {
        return this.expandedStepKeys().has(step.key);
    }

    toggleStep(step: NodeStreamToolStep): void {
        this.expandedStepKeys.update((current) => {
            const next = new Set(current);
            if (next.has(step.key)) {
                next.delete(step.key);
            } else {
                next.add(step.key);
            }
            return next;
        });
    }

    isStepError(step: NodeStreamToolStep): boolean {
        return step.result?.is_error === true;
    }

    getStepSummary(step: NodeStreamToolStep): string {
        return step.call?.name ?? step.result?.name ?? 'Tool step';
    }

    truncate(str: string, max: number): string {
        return str.length > max ? str.substring(0, max) + '...' : str;
    }
}
