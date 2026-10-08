import { NgStyle, NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    EventEmitter,
    inject,
    Input,
    input,
    OnInit,
    Output,
    output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { EFResizeHandleType, FFlowModule } from '@foblex/flow';
import { AppSvgIconComponent, GoToButtonComponent } from '@shared/components';
import { KEY_VALUE_MODE_COLORS, NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';
import { flowUrl } from '@shared/utils';

import { AgentDefinitionsApiService } from '../../../features/agent-definitions/services/agent-definitions-api.service';
import { KeyValueTablesStorageService } from '../../../features/key-value-tables/services/key-value-tables-storage.service';
import { CAPTION_TABLE_NAME_LIMIT, keyValueSummaryParts } from '../../core/constants/key-value-mode-visuals';
import { ClickOrDragDirective } from '../../core/directives/click-or-drag.directive';
import { getNodeTitle } from '../../core/enums/node-title.util';
import {
    AgentNodeModel,
    ClassificationDecisionTableNodeModel,
    DecisionTableNodeModel,
    EndNodeModel,
    GraphNoteModel,
    KeyValueNodeModel,
    LLMNodeModel,
    NodeModel,
    PythonNodeModel,
    ScheduleTriggerNodeModel,
    StartNodeModel,
    SubGraphNodeModel,
    TaskNodeModel,
    ToolNodeModel,
} from '../../core/models/node.model';
import { CustomPortId } from '../../core/models/port.model';
import { FlowService } from '../../services/flow.service';
import { FlowReadOnlyService } from '../../services/flow-readonly.service';
import { ClassificationDecisionTableNodeComponent } from '../nodes-components/classification-decision-table-node/classification-decision-table-node.component';
import { DecisionTableNodeComponent } from '../nodes-components/decision-table-node/decision-table-node.component';
import { GraphNoteComponent } from '../nodes-components/graph-note/graph-note.component';

@Component({
    selector: 'app-flow-base-node',
    templateUrl: './flow-base-node.component.html',
    styleUrls: ['./flow-base-node.component.scss'],
    imports: [
        FFlowModule,
        NgStyle,
        NgTemplateOutlet,
        ClickOrDragDirective,
        DecisionTableNodeComponent,
        ClassificationDecisionTableNodeComponent,
        GraphNoteComponent,
        GoToButtonComponent,
        AppSvgIconComponent,
        MatTooltipModule,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '[class]': 'getNodeClass()',
    },
})
export class FlowBaseNodeComponent implements OnInit {
    private readonly agentDefinitionsApi = inject(AgentDefinitionsApiService);
    private readonly llmConfigStorage = inject(LlmConfigStorageService);
    private readonly keyValueTablesStorage = inject(KeyValueTablesStorageService);
    private readonly destroyRef = inject(DestroyRef);
    public readonly isReadOnly = inject(FlowReadOnlyService).isReadOnly;

    @Input({ required: true }) node!: NodeModel;
    @Output() fNodeSizeChange = new EventEmitter<{
        width: number;
        height: number;
    }>();
    @Output() editClicked = new EventEmitter<NodeModel>();
    @Output() deleteClicked = new EventEmitter<NodeModel>();
    readonly unpackClicked = output<void>();
    public isExpanded = signal(false);
    public isToggleDisabled = signal(false);
    multiSelectActive = input<boolean>(false);

    @Output() portMouseenter = new EventEmitter<void>();
    @Output() portMouseleave = new EventEmitter<void>();

    public NodeType = NodeType;
    public readonly eResizeHandleType = EFResizeHandleType;

    public portConnections = computed((): Record<string, CustomPortId[]> => {
        if (!this.node) {
            return {};
        }

        if (!this.node.ports) {
            return {};
        }

        const fullMap = this.flowService.portConnectionsMap();
        return this.node.ports.reduce(
            (acc, port) => {
                acc[port.id] = fullMap[port.id] || [];
                return acc;
            },
            {} as Record<string, CustomPortId[]>
        );
    });

    constructor(
        public flowService: FlowService,
        private cdr: ChangeDetectorRef
    ) {}

    public ngOnInit(): void {
        if (this.node.type === NodeType.KEY_VALUE && this.keyValueTablesStorage.tables().length === 0) {
            this.keyValueTablesStorage.loadTables().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        }
    }

    public onDeleteClick(event: MouseEvent): void {
        event.preventDefault();
        event.stopPropagation();
        this.deleteClicked.emit(this.node);
    }

    public onEditClick(event?: MouseEvent): void {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        if (this.isBlockedSubgraph) {
            return;
        }
        this.editClicked.emit(this.node);
    }

    public onUnpackClick(event: MouseEvent): void {
        event.preventDefault();
        event.stopPropagation();
        if (this.isBlockedSubgraph) return;
        this.unpackClicked.emit();
    }

    trackByPort(index: number, port: { id: string }): string {
        return port.id;
    }

    public getNodeClass(): string {
        const blockedClass = this.isBlockedSubgraph ? ' is-blocked' : '';
        switch (this.node.type) {
            case NodeType.AGENT:
                return 'type-agent';
            case NodeType.TASK:
                return 'type-task';
            case NodeType.TOOL:
                return 'type-tool';
            case NodeType.LLM:
                return 'type-llm';
            case NodeType.PYTHON:
                return 'type-python';
            case NodeType.START:
                return 'type-start';
            case NodeType.TABLE:
                return 'type-table';
            case NodeType.CLASSIFICATION_TABLE:
                return 'type-table';
            case NodeType.NOTE:
                return 'type-note';
            default:
                return `type-default${blockedClass}`;
        }
    }

    public get agentNode() {
        return this.node.type === NodeType.AGENT ? (this.node as AgentNodeModel) : null;
    }

    public get taskNode() {
        return this.node.type === NodeType.TASK ? (this.node as TaskNodeModel) : null;
    }

    public get toolNode() {
        return this.node.type === NodeType.TOOL ? (this.node as ToolNodeModel) : null;
    }

    public get llmNode() {
        return this.node.type === NodeType.LLM ? (this.node as LLMNodeModel) : null;
    }

    public get pythonNode() {
        return this.node.type === NodeType.PYTHON ? (this.node as PythonNodeModel) : null;
    }

    public get decisionTableNode(): DecisionTableNodeModel | null {
        return this.node.type === NodeType.TABLE ? (this.node as DecisionTableNodeModel) : null;
    }

    public get classificationTableNode(): ClassificationDecisionTableNodeModel | null {
        return this.node.type === NodeType.CLASSIFICATION_TABLE
            ? (this.node as ClassificationDecisionTableNodeModel)
            : null;
    }

    public get startNode() {
        return this.node.type === NodeType.START ? (this.node as StartNodeModel) : null;
    }
    public get endNode() {
        return this.node.type === NodeType.END ? (this.node as EndNodeModel) : null;
    }
    public get noteNode() {
        return this.node.type === NodeType.NOTE ? (this.node as GraphNoteModel) : null;
    }
    public get isBlockedSubgraph(): boolean {
        return this.node?.type === NodeType.SUBGRAPH && !!this.node.isBlocked;
    }

    public get hasNumberChip(): boolean {
        if (this.node.type === NodeType.START || this.node.type === NodeType.END) return false;
        return this.node.nodeNumber != null;
    }

    public get hasDeleteChip(): boolean {
        return this.node.type !== NodeType.START && !this.isReadOnly();
    }

    public get keyValueNode(): KeyValueNodeModel | null {
        return this.node.type === NodeType.KEY_VALUE ? (this.node as KeyValueNodeModel) : null;
    }

    /** A Key-Value node's header icon and its colour: the type's own, whatever its mode or saved metadata. */
    public get keyValueHeader(): { icon: string; color: string } | null {
        if (!this.keyValueNode) return null;
        return { icon: NODE_ICONS[NodeType.KEY_VALUE], color: NODE_COLORS[NodeType.KEY_VALUE] };
    }

    /** The colour of a Key-Value node's mode stripe, as a ready-to-use `var(--...)` string. */
    public get keyValueModeStripeColor(): string | null {
        const node = this.keyValueNode;
        return node ? KEY_VALUE_MODE_COLORS[node.data.mode] : null;
    }

    /** "Mode / Table / N keys" in full, and as the parts the #N tab shows, its table name cut short. */
    public get keyValueSummary(): { full: string; captionParts: string[] } | null {
        const node = this.keyValueNode;
        if (!node) return null;
        const table = this.keyValueTablesStorage.tables().find((t) => t.id === node.data.key_value_table);
        const tableName = table?.name ?? null;
        const keyCount = node.data.entries.length;
        return {
            full: keyValueSummaryParts(node.data.mode, tableName, keyCount).join(' / '),
            captionParts: keyValueSummaryParts(node.data.mode, tableName, keyCount, CAPTION_TABLE_NAME_LIMIT),
        };
    }

    public get hasMissingKeyValueTable(): boolean {
        return !!this.keyValueNode && this.keyValueNode.data.key_value_table === null;
    }

    private get assignedAgentDefinitionId(): number | null {
        return this.agentNode?.data.agent_definition ?? this.taskNode?.data.agent_definition ?? null;
    }

    public get hasMissingAgentLlm(): boolean {
        const agentId = this.assignedAgentDefinitionId;
        if (agentId == null) return false;
        const agent = this.agentDefinitionsApi.definitions().find((a) => a.id === agentId);
        if (!agent) return false;
        if (agent.llm_config == null) return true;
        if (!this.llmConfigStorage.isConfigsLoaded()) return false;
        const availableIds = new Set(this.llmConfigStorage.configs().map((c) => c.id));
        return !availableIds.has(agent.llm_config);
    }

    public get agentLlmWarningTooltip(): string {
        const agentId = this.assignedAgentDefinitionId;
        if (agentId == null) return '';
        const agent = this.agentDefinitionsApi.definitions().find((a) => a.id === agentId);
        if (!agent) return '';
        if (agent.llm_config == null) return 'The assigned agent has no LLM model configured.';
        if (!this.llmConfigStorage.isConfigsLoaded()) return '';
        const availableIds = new Set(this.llmConfigStorage.configs().map((c) => c.id));
        if (!availableIds.has(agent.llm_config)) {
            return "The assigned agent's LLM model was deleted. Reassign a model to the agent.";
        }
        return '';
    }

    public get hasMissingAgent(): boolean {
        // Only agent/task nodes carry an agent assignment.
        if (this.agentNode === null && this.taskNode === null) return false;
        if (this.node.backendId == null) return false;
        return this.assignedAgentDefinitionId == null;
    }

    public get missingAgentTooltip(): string {
        return this.hasMissingAgent
            ? 'This node has no agent assigned (the agent may have been deleted). Assign an agent to this node.'
            : '';
    }

    public getNodeTitle(): string {
        return getNodeTitle(this.node);
    }

    onNodeSizeChanged(size: { width: number; height: number }): void {
        this.fNodeSizeChange.emit(size);
    }

    get isScheduleTriggerActive(): boolean {
        return (
            this.node.type === NodeType.SCHEDULE_TRIGGER &&
            (this.node as ScheduleTriggerNodeModel).data?.isActive === true
        );
    }

    public getSelectedFlowUrl(): string | null {
        if (this.node?.type !== NodeType.SUBGRAPH) return null;
        if (this.isBlockedSubgraph) return null;
        const flowId = Number((this.node as SubGraphNodeModel).data?.id);
        if (!Number.isFinite(flowId) || flowId <= 0) return null;
        return flowUrl(flowId);
    }
}
