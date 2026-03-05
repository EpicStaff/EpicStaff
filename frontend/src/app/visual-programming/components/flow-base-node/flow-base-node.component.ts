import {
    Component,
    Input,
    ChangeDetectionStrategy,
    computed,
    signal,
    EventEmitter,
    Output,
    ViewChild,
    ElementRef,
    effect,
    ChangeDetectorRef,
} from '@angular/core';
import { FFlowModule, EFResizeHandleType } from '@foblex/flow';
import {
    NgFor,
    NgClass,
    NgSwitch,
    NgSwitchCase,
    NgSwitchDefault,
    NgIf,
    NgStyle,
    NgTemplateOutlet,
} from '@angular/common';

import { ClickOrDragDirective } from '../../core/directives/click-or-drag.directive';
import {
    NodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    NoteNodeModel,
} from '../../core/models/node.model';
import { NodeType } from '../../core/enums/node-type';
import { FlowService } from '../../services/flow.service';
import { CustomPortId } from '../../core/models/port.model';

import { ConditionalEdgeNodeComponent } from '../nodes-components/conditional-edge/conditional-edge.component';
import { DecisionTableNodeComponent } from '../nodes-components/decision-table-node/decision-table-node.component';
import { NoteNodeComponent } from '../nodes-components/note-node/note-node.component';
import { getNodeTitle } from '../../core/enums/node-title.util';
import { ResizeHandleComponent } from '../resize-handle/resize-handle.component';
import { FlowNodeVariablesOverlayComponent } from './flow-node-variables-overlay.component';
import { GoToButtonComponent } from '../../../shared/components/go-to-button/go-to-button.component';
import { flowUrl } from '../../../shared/utils/flow-links';

@Component({
    selector: 'app-flow-base-node',
    templateUrl: './flow-base-node.component.html',
    styleUrls: ['./flow-base-node.component.scss'],
    standalone: true,
    imports: [
        FFlowModule,
        NgIf,
        NgStyle,
        NgTemplateOutlet,
        ClickOrDragDirective,
        ConditionalEdgeNodeComponent,
        DecisionTableNodeComponent,
        NoteNodeComponent,
        FlowNodeVariablesOverlayComponent,
        GoToButtonComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '[class]': 'getNodeClass()',
    },
})
export class FlowBaseNodeComponent {
    @Input({ required: true }) node!: NodeModel;
    @Output() fNodeSizeChange = new EventEmitter<{
        width: number;
        height: number;
    }>();
    @Output() editClicked = new EventEmitter<NodeModel>();
    public isExpanded = signal(false);
    public isToggleDisabled = signal(false);
    @Input() showVariables: boolean = false;

    @Output() projectExpandToggled = new EventEmitter<ProjectNodeModel>();

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
        return this.node.ports.reduce((acc, port) => {
            acc[port.id] = fullMap[port.id] || [];
            return acc;
        }, {} as Record<string, CustomPortId[]>);
    });

    constructor(
        public flowService: FlowService,
        private cdr: ChangeDetectorRef
    ) {}

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
            case NodeType.NOTE:
                return 'type-note';
            default:
                return `type-default${blockedClass}`;
        }
    }

    // Getters for specific node types
    public get agentNode() {
        return this.node.type === NodeType.AGENT ? (this.node as any) : null;
    }

    public get taskNode() {
        return this.node.type === NodeType.TASK ? (this.node as any) : null;
    }

    public get toolNode() {
        return this.node.type === NodeType.TOOL ? (this.node as any) : null;
    }

    public get llmNode() {
        return this.node.type === NodeType.LLM ? (this.node as any) : null;
    }

    public get pythonNode() {
        return this.node.type === NodeType.PYTHON ? (this.node as any) : null;
    }

    public get edgeNode() {
        return this.node.type === NodeType.EDGE ? (this.node as any) : null;
    }

    public get tableNode() {
        return this.node.type === NodeType.TABLE ? (this.node as any) : null;
    }

    public get startNode() {
        return this.node.type === NodeType.START ? (this.node as any) : null;
    }
    public get endNode() {
        return this.node.type === NodeType.END ? (this.node as any) : null;
    }
    public get noteNode() {
        return this.node.type === NodeType.NOTE
            ? (this.node as NoteNodeModel)
            : null;
    }
    public get isBlockedSubgraph(): boolean {
        return this.node?.type === NodeType.SUBGRAPH && !!this.node.isBlocked;
    }
    public onExpandProjectClick(): void {
        this.projectExpandToggled.emit(this.node as ProjectNodeModel);
    }

    public onUngroupClick(event: MouseEvent): void {
        event.preventDefault();
        event.stopPropagation();

        const updatedNode: NodeModel = { ...this.node, parentId: null };

        this.flowService.updateNode(updatedNode);
    }

    public getNodeTitle(): string {
        return getNodeTitle(this.node);
    }

    onNodeSizeChanged(size: { width: number; height: number }): void {
        this.fNodeSizeChange.emit(size);
    }

    public getSelectedFlowUrl(): string | null {
        if (this.node?.type !== NodeType.SUBGRAPH) return null;
        if (this.isBlockedSubgraph) return null;
        const flowId = Number((this.node as any)?.data?.id);
        if (!Number.isFinite(flowId) || flowId <= 0) return null;
        return flowUrl(flowId);
    }
}
