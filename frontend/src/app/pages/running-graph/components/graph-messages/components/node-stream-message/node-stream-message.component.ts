import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { expandCollapseAnimation } from '../../../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import {
    AgentNodeStreamMessageData,
    GraphMessage,
    MessageType,
    NodeStreamTaskRef,
    NodeStreamToolCallData,
    NodeStreamToolResultData,
    TaskNodeStreamMessageData,
} from '../../../../models/graph-session-message.model';

type NodeStreamMessageData = TaskNodeStreamMessageData | AgentNodeStreamMessageData;
type NodeStreamType = MessageType.TASK_NODE_STREAM | MessageType.AGENT_NODE_STREAM;

interface NodeStreamStep {
    key: string;
    stepId: number;
    toolCall: NodeStreamToolCallData | null;
    toolResult: NodeStreamToolResultData | null;
    task: NodeStreamTaskRef | null;
}

interface NodeStreamTaskGroup {
    key: string;
    taskName: string | null;
    order: number;
    steps: NodeStreamStep[];
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
    animations: [expandCollapseAnimation],
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
                    @if (totalStepCount() > 0) {
                        <span class="step-count">
                            {{ totalStepCount() }} step{{ totalStepCount() !== 1 ? 's' : '' }}
                        </span>
                    }
                </div>
            </div>

            <!-- Steps -->
            <div
                class="collapsible-content"
                [@expandCollapse]="isExpanded() ? 'expanded' : 'collapsed'"
            >
                @if (totalStepCount() > 0) {
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
                                    @for (step of group.steps; track step.key) {
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
                                                [@expandCollapse]="isStepExpanded(step) ? 'expanded' : 'collapsed'"
                                            >
                                                <div class="step-content">
                                                    @if (step.toolCall; as call) {
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

                                                    @if (step.toolResult; as result) {
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
                                    }
                                </div>
                            </div>
                        }
                    </div>
                }
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
            overflow: hidden;
            position: relative;

            &.ng-animating {
                overflow: hidden;
            }
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

    // Group all stream events for this node+type by step_id, pairing tool_call/tool_result
    // that share a step_id (mirrors the step_id consolidation done by app-code-agent-stream-message).
    readonly steps = computed<NodeStreamStep[]>(() => {
        const message = this.message();
        const nodeName = message.name;
        const type = message.message_data.message_type;

        const stepMap = new Map<number, NodeStreamStep>();
        const order: number[] = [];

        for (const msg of this.allMessages()) {
            const data = msg.message_data;
            if (!data || data.message_type !== type || msg.name !== nodeName) continue;

            const streamData = data as NodeStreamMessageData;
            const stepId = streamData.step_id;
            let step = stepMap.get(stepId);
            if (!step) {
                step = {
                    key: `step_${stepId}`,
                    stepId,
                    toolCall: null,
                    toolResult: null,
                    task: null,
                };
                stepMap.set(stepId, step);
                order.push(stepId);
            }

            if (streamData.event === 'tool_call') {
                step.toolCall = streamData.data as NodeStreamToolCallData;
            } else if (streamData.event === 'tool_result') {
                step.toolResult = streamData.data as NodeStreamToolResultData;
            }
            if (!step.task && streamData.data.task) {
                step.task = streamData.data.task;
            }
        }

        return order.map((id) => stepMap.get(id)!);
    });

    // AgentNode steps carry an optional `data.task` — group under sub-task headers ordered
    // by task.order when present, otherwise fall back to a single flat, header-less list.
    readonly taskGroups = computed<NodeStreamTaskGroup[]>(() => {
        const steps = this.steps();
        const hasTaskInfo = steps.some((step) => !!step.task);
        if (!hasTaskInfo) {
            return [{ key: '__flat__', taskName: null, order: 0, steps }];
        }

        const groups = new Map<string, NodeStreamTaskGroup>();
        for (const step of steps) {
            const key = step.task ? `task_${step.task.order}_${step.task.name}` : '__untasked__';
            let group = groups.get(key);
            if (!group) {
                group = {
                    key,
                    taskName: step.task ? step.task.name : null,
                    order: step.task ? step.task.order : Number.MAX_SAFE_INTEGER,
                    steps: [],
                };
                groups.set(key, group);
            }
            group.steps.push(step);
        }
        return [...groups.values()].sort((a, b) => a.order - b.order);
    });

    readonly totalStepCount = computed(() => this.steps().length);

    toggleMessage(): void {
        this.isExpanded.update((value) => !value);
    }

    isStepExpanded(step: NodeStreamStep): boolean {
        return this.expandedStepKeys().has(step.key);
    }

    toggleStep(step: NodeStreamStep): void {
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

    isStepError(step: NodeStreamStep): boolean {
        return step.toolResult?.is_error === true;
    }

    getStepSummary(step: NodeStreamStep): string {
        return step.toolCall?.name ?? step.toolResult?.name ?? `Step ${step.stepId}`;
    }

    truncate(str: string, max: number): string {
        return str.length > max ? str.substring(0, max) + '...' : str;
    }
}
