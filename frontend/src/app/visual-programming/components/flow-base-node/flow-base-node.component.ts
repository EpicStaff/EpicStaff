import { NgStyle, NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    EventEmitter,
    inject,
    Input,
    input,
    Output,
    signal,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { EFResizeHandleType, FFlowModule } from '@foblex/flow';

import { AgentDefinitionsApiService } from '../../../features/agent-definitions/services/agent-definitions-api.service';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GoToButtonComponent } from '../../../shared/components/go-to-button/go-to-button.component';
import { LlmConfigStorageService } from '../../../shared/services/llms/llm-config-storage.service';
import { flowUrl } from '../../../shared/utils/flow-links';
import { ClickOrDragDirective } from '../../core/directives/click-or-drag.directive';
import { getNodeTitle } from '../../core/enums/node-title.util';
import { NodeType } from '../../core/enums/node-type';
import {
    AgentNodeModel,
    ClassificationDecisionTableNodeModel,
    DecisionTableNodeModel,
    EdgeNodeModel,
    EndNodeModel,
    GraphNoteModel,
    LLMNodeModel,
    NodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    ScheduleTriggerNodeModel,
    StartNodeModel,
    SubGraphNodeModel,
    TaskNodeModel,
    ToolNodeModel,
} from '../../core/models/node.model';
import { CustomPortId } from '../../core/models/port.model';
import { FlowService } from '../../services/flow.service';
import { ClassificationDecisionTableNodeComponent } from '../nodes-components/classification-decision-table-node/classification-decision-table-node.component';
import { ConditionalEdgeNodeComponent } from '../nodes-components/conditional-edge/conditional-edge.component';
import { DecisionTableNodeComponent } from '../nodes-components/decision-table-node/decision-table-node.component';
import { GraphNoteComponent } from '../nodes-components/graph-note/graph-note.component';
import { FlowNodeVariablesOverlayComponent } from './flow-node-variables-overlay.component';

@Component({
    selector: 'app-flow-base-node',
    templateUrl: './flow-base-node.component.html',
    styleUrls: ['./flow-base-node.component.scss'],
    imports: [
        FFlowModule,
        NgStyle,
        NgTemplateOutlet,
        ClickOrDragDirective,
        ConditionalEdgeNodeComponent,
        DecisionTableNodeComponent,
        ClassificationDecisionTableNodeComponent,
        GraphNoteComponent,
        FlowNodeVariablesOverlayComponent,
        GoToButtonComponent,
        AppSvgIconComponent,
        MatTooltipModule,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '[class]': 'getNodeClass()',
    },
})
export class FlowBaseNodeComponent {
    private readonly agentDefinitionsApi = inject(AgentDefinitionsApiService);
    private readonly llmConfigStorage = inject(LlmConfigStorageService);

    @Input({ required: true }) node!: NodeModel;
    @Output() fNodeSizeChange = new EventEmitter<{
        width: number;
        height: number;
    }>();
    @Output() editClicked = new EventEmitter<NodeModel>();
    @Output() deleteClicked = new EventEmitter<NodeModel>();
    public isExpanded = signal(false);
    public isToggleDisabled = signal(false);
    @Input() showVariables: boolean = false;
    multiSelectActive = input<boolean>(false);

    @Output() projectExpandToggled = new EventEmitter<ProjectNodeModel>();
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
            case NodeType.PROJECT:
                return 'type-project';
            case NodeType.TOOL:
                return 'type-tool';
            case NodeType.LLM:
                return 'type-llm';
            case NodeType.PYTHON:
                return 'type-python';
            case NodeType.EDGE:
                return 'type-edge';
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

    public get edgeNode() {
        return this.node.type === NodeType.EDGE ? (this.node as EdgeNodeModel) : null;
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

    public onExpandProjectClick(): void {
        this.projectExpandToggled.emit(this.node as ProjectNodeModel);
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
