import {
  Component,
  Input,
  OnChanges,
  SimpleChanges,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';

import {
  GraphMessage,
  MessageType,
} from '../../models/graph-session-message.model';
import { UpdateSessionStatusMessageData } from '../../models/graph-session-message.model';
import { CrewNode } from '../../../flows-page/components/flow-visual-programming/models/crew-node.model';
import { GetLLMNodeRequest } from '../../../flows-page/components/flow-visual-programming/models/llm-node.model';
import { PythonNode } from '../../../flows-page/components/flow-visual-programming/models/python-node.model';
import { GraphDto } from '../../../../features/flows/models/graph.model';

interface NodeStatus {
  node: CrewNode | PythonNode | GetLLMNodeRequest;
  status: 'complete' | 'in_progress' | 'error' | 'waiting' | 'not_started';
}

@Component({
  selector: 'app-flow-representation',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="flow-container">
      <div class="flow-content">
        <div *ngIf="orderedNodesStatus?.length; else noNodes">
          <ul>
            <li
              *ngFor="let item of orderedNodesStatus; trackBy: trackByNode"
              [ngClass]="getItemClass(item.status)"
            >
              <div class="node-name">{{ item.node.node_name }}</div>
              <div class="status-badge" [ngClass]="getStatusClass(item.status)">
                <i
                  [ngClass]="getStatusIcon(item.status)"
                  aria-hidden="true"
                ></i>
                {{ getStatusText(item.status) }}
              </div>
            </li>
          </ul>
        </div>
        <ng-template #noNodes>
          <div class="placeholder">No nodes found</div>
        </ng-template>
      </div>
    </div>
  `,
  styles: `
      .flow-container {
        height: 100%;
        width: 400px !important;
        
        overflow-y: auto;
        
  background-color: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
      }
  
      .flow-content {
        flex: 1;
        overflow: auto;
        display: flex;
        align-items: flex-start;
        flex-direction: column;
        width: 100%;
        max-width: 100%;
        padding: 1rem 3.8rem;
  
        & > div {
          width: 100%;
        }
      }
  
      .section-title {
        font-size: 18px;
        font-weight: 500;
        margin-bottom: 1rem;
        color: var(--white);
        letter-spacing: -0.02em;
      }
  
      ul {
        list-style: none;
        padding: 0;
        margin: 0;
        width: 100%;
        display: block;
      }
  
      li {
        padding: 0.75rem 1rem;
        margin-bottom: 1rem;
        border-radius: 6px;
        background: var(--gray-850);
        border: 1px solid var(--gray-800);
        transition: background-color 0.2s, border-color 0.2s;
  
        &:last-child {
          margin-bottom: 0.5rem;
        }
  
        &:hover {
          background: var(--gray-800);
          border-color: var(--gray-750);
        }
      }
  
      .node-name {
        font-size: 1rem;
        font-weight: 500;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin-bottom: 0.5rem;
      }
  
      .status-badge {
        font-size: 0.8rem;
        margin-top: 0rem;
        font-weight: 500;
        padding: 0.25rem 0.75rem;
        border-radius: 12px;
        display: inline-flex;
        align-items: center;
        gap: 6px;
  
        i {
          font-size: 14px;
        }
      }
  
      /* Updated colors and styles to match the dialog and header component */
      .status-complete {
        background-color: rgba(80, 205, 137, 0.15);
        color: #6bdb9a;
      }
  
      .status-in_progress {
        background-color: rgba(41, 121, 255, 0.15);
        color: #5e9eff;
        animation: pulse 1.5s infinite ease-in-out;
      }
  
      .status-error {
        background-color: rgba(255, 76, 76, 0.15);
        color: #ff7a7a;
      }
  
      .status-waiting {
        background-color: rgba(255, 170, 0, 0.15);
        color: #ffc14d;
      }
  
      .status-not_started {
        background-color: rgba(150, 150, 150, 0.15);
        color: #9898a9;
      }
  
      @keyframes pulse {
        0% {
          opacity: 1;
        }
        50% {
          opacity: 0.7;
        }
        100% {
          opacity: 1;
        }
      }
  
      .placeholder {
        color: var(--gray-500);
        font-style: italic;
        text-align: center;
        width: 100%;
        padding: 2rem;
        background: var(--gray-850);
        border-radius: 6px;
        margin-top: 1rem;
      }
  
      /* Item active state */
      .item-active {
        border-left: 3px solid #5e9eff !important;
      }
    `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowRepresentationComponent implements OnChanges {
  @Input() graphData: GraphDto | null = null;
  @Input() messages: GraphMessage[] = [];

  orderedNodes: (CrewNode | PythonNode | GetLLMNodeRequest)[] = [];

  orderedNodesStatus: NodeStatus[] = [];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['graphData'] && this.graphData) {
      //   this.orderedNodes = this.getOrderedNodes(this.graphData);
    }
    if ((changes['messages'] || changes['graphData']) && this.graphData) {
      this.calculateNodesStatus();
    }
  }

  private getOrderedNodes(
    graph: GraphDto
  ): (CrewNode | PythonNode | GetLLMNodeRequest)[] {
    const nodesMap: {
      [nodeName: string]: CrewNode | PythonNode | GetLLMNodeRequest;
    } = {};
    const idToName: { [id: number]: string } = {};
    const nameToId: { [name: string]: number } = {};

    graph.crew_node_list.forEach((node) => {
      nodesMap[node.node_name] = node;
      idToName[node.id] = node.node_name;
      nameToId[node.node_name] = node.id;
    });
    graph.python_node_list.forEach((node) => {
      nodesMap[node.node_name] = node;
      idToName[node.id] = node.node_name;
      nameToId[node.node_name] = node.id;
    });
    graph.llm_node_list.forEach((node) => {
      nodesMap[node.node_name] = node;
      idToName[node.id] = node.node_name;
      nameToId[node.node_name] = node.id;
    });

    if (graph.start_node_list?.[0]) {
      const startId = graph.start_node_list[0].id;
      idToName[startId] = '__start__';
      nameToId['__start__'] = startId;
    }

    const ordered: (CrewNode | PythonNode | GetLLMNodeRequest)[] = [];
    const startId = graph.start_node_list?.[0]?.id;
    if (startId == null) return ordered;

    let currentId: number | undefined = startId;
    while (currentId != null) {
      const nodeName = idToName[currentId];
      if (!nodeName) break;
      const node = nodesMap[nodeName];
      if (node) ordered.push(node);

      const nextEdge = graph.edge_list.find(
        (edge) => edge.start_node_id === currentId
      );
      currentId = nextEdge?.end_node_id;
    }
    return ordered;
  }

  /**
   * Computes the execution status for each ordered node based on the messages.
   * Scenarios:
   * - 'complete': has both start and finish messages.
   * - 'in_progress': has a start message but no finish.
   * - 'error': start followed by an error message.
   * - 'waiting': has a wait_for_user update message (only if no finish message exists).
   * - 'not_started': no messages found.
   */
  private calculateNodesStatus(): void {
    this.orderedNodesStatus = this.orderedNodes.map((node) => {
      const nodeMessages = this.messages.filter(
        (msg) => msg.name === node.node_name
      );
      let status: NodeStatus['status'] = 'not_started';
      if (nodeMessages.length > 0) {
        if (
          nodeMessages.some(
            (msg) => msg.message_data?.message_type === MessageType.ERROR
          )
        ) {
          status = 'error';
        }
        // If both start and finish messages exist, mark as complete.
        else if (
          nodeMessages.some(
            (msg) => msg.message_data?.message_type === MessageType.START
          ) &&
          nodeMessages.some(
            (msg) => msg.message_data?.message_type === MessageType.FINISH
          )
        ) {
          status = 'complete';
        } else if (
          nodeMessages.some(
            (msg) =>
              msg.message_data?.message_type ===
                MessageType.UPDATE_SESSION_STATUS &&
              (msg.message_data as UpdateSessionStatusMessageData).status ===
                'wait_for_user'
          )
        ) {
          status = 'waiting';
        } else if (
          nodeMessages.some(
            (msg) => msg.message_data?.message_type === MessageType.START
          )
        ) {
          status = 'in_progress';
        }
      }
      return { node, status };
    });
  }

  trackByNode(index: number, item: NodeStatus): number {
    return item.node.id || index;
  }

  getStatusClass(status: NodeStatus['status']): string {
    switch (status) {
      case 'complete':
        return 'status-complete';
      case 'in_progress':
        return 'status-in_progress';
      case 'error':
        return 'status-error';
      case 'waiting':
        return 'status-waiting';
      case 'not_started':
        return 'status-not_started';
      default:
        return '';
    }
  }

  getStatusIcon(status: NodeStatus['status']): string {
    switch (status) {
      case 'complete':
        return 'ti ti-check';
      case 'in_progress':
        return 'ti ti-player-play';
      case 'error':
        return 'ti ti-alert-triangle';
      case 'waiting':
        return 'ti ti-hourglass';
      case 'not_started':
        return 'ti ti-circle-dot';
      default:
        return '';
    }
  }

  getItemClass(status: NodeStatus['status']): string {
    return status === 'in_progress' ? 'item-active' : '';
  }

  getStatusText(status: NodeStatus['status']): string {
    switch (status) {
      case 'complete':
        return 'Completed';
      case 'in_progress':
        return 'Running';
      case 'error':
        return 'Error';
      case 'waiting':
        return 'Waiting for User';
      case 'not_started':
        return 'Not Active';
      default:
        return '';
    }
  }
}
