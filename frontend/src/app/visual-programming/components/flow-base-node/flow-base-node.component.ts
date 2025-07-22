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
} from '@angular/common';

import { AgentNodeComponent } from '../nodes-components/agent-node/agent-node.component';
import { TaskNodeComponent } from '../nodes-components/task-node/task-node.component';
import { ClickOrDragDirective } from './directives/click-or-drag.directive';
import {
  NodeModel,
  ProjectNodeModel,
  PythonNodeModel,
  BaseNodeModel,
  NoteNodeModel,
} from '../../core/models/node.model';
import { NodeType } from '../../core/enums/node-type';
import { FlowService } from '../../services/flow.service';
import { CustomPortId } from '../../core/models/port.model';
import { ToolNodeComponent } from '../nodes-components/tool-node/tool-node.component';
import { LlmNodeComponent } from '../nodes-components/llm-node/llm-node.component';
import { ProjectNodeComponent } from '../nodes-components/project-node/project-node.component';
import { PythonNodeComponent } from '../nodes-components/python-node/python-node.component';
import { ConditionalEdgeNodeComponent } from '../nodes-components/conditional-edge/conditional-edge.component';
import { DecisionTableNodeComponent } from '../nodes-components/decision-table-node/decision-table-node.component';
import { NoteNodeComponent } from '../nodes-components/note-node/note-node.component';
import { getNodeTitle } from '../../core/enums/node-title.util';
import { ResizeHandleComponent } from '../resize-handle/resize-handle.component';

@Component({
  selector: 'app-flow-base-node',
  templateUrl: './flow-base-node.component.html',
  styleUrls: ['./flow-base-node.component.scss'],
  standalone: true,
  imports: [
    FFlowModule,
    NgIf,
    NgStyle,
    ClickOrDragDirective,
    ConditionalEdgeNodeComponent,
    AgentNodeComponent,
    TaskNodeComponent,

    DecisionTableNodeComponent,
    NoteNodeComponent,
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

    // Add null check for ports
    if (!this.node.ports) {
      return {};
    }

    const fullMap = this.flowService.portConnectionsMap();
    return this.node.ports.reduce((acc, port) => {
      // Example logic to combine port information:
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
    this.editClicked.emit(this.node);
  }

  trackByPort(index: number, port: { id: string }): string {
    return port.id;
  }

  public getNodeClass(): string {
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
        return 'type-default';
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
  public get noteNode() {
    return this.node.type === NodeType.NOTE
      ? (this.node as NoteNodeModel)
      : null;
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

  public isBaseNode(node: NodeModel): node is BaseNodeModel & NodeModel {
    return 'input_map' in node && 'output_variable_path' in node;
  }

  public objectKeys(obj: any): string[] {
    return Object.keys(obj || {});
  }
}
