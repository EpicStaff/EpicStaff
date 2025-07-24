import {
  Component,
  Input,
  ChangeDetectionStrategy,
  Output,
  EventEmitter,
} from '@angular/core';
import { NgFor } from '@angular/common';
import { NodeType } from '../../../core/enums/node-type';
import { NODE_COLORS, NODE_ICONS } from '../../../core/enums/node-config';

interface FlowGraphBlock {
  label: string;
  type: NodeType;
  icon: string;
  color: string;
}

@Component({
  selector: 'app-flow-graph-core-menu',
  standalone: true,
  template: `
    <ul>
      <li
        *ngFor="let block of filteredBlocks"
        (click)="onBlockClicked(block.type)"
        [style.border-left-color]="block.color"
      >
        <i [class]="block.icon" [style.color]="block.color"></i>
        {{ block.label }}
        <i class="ti ti-plus plus-icon"></i>
      </li>
    </ul>
  `,
  styles: [
    `
      ul {
        list-style: none;
        padding: 0 16px;
        margin: 0;
      }
      li {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 16px;
        border-radius: 8px;
        gap: 14px;
        cursor: pointer;
        transition: background 0.2s ease;
        position: relative;
      }
      li:hover {
        background: #2a2a2a;
      }
      li i {
        font-size: 16px;
        color: #bbb; /* Fallback color */
        transition: color 0.2s ease;
      }
      li:hover i {
        color: inherit; /* Keep the color from [style.color]="block.color" */
      }
      .plus-icon {
        margin-left: auto;
        font-size: 18px;
        color: #bbb;
        opacity: 0;
        transition: opacity 0.2s ease, color 0.2s ease;
      }
      li:hover .plus-icon {
        opacity: 1;
        color: inherit; /* Match the block color on hover */
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgFor],
})
export class FlowGraphCoreMenuComponent {
  @Input() public searchTerm: string = '';

  @Output() public nodeSelected: EventEmitter<{
    type: NodeType;
    data: any;
  }> = new EventEmitter();

  // Use NodeType-based mappings for icon & color
  public blocks: FlowGraphBlock[] = [
    {
      label: 'Python Code Node',
      type: NodeType.PYTHON,
      icon: NODE_ICONS[NodeType.PYTHON],
      color: NODE_COLORS[NodeType.PYTHON],
    },
    {
      label: 'Conditional Edge',
      type: NodeType.EDGE,
      icon: NODE_ICONS[NodeType.EDGE],
      color: NODE_COLORS[NodeType.EDGE],
    },
    {
      label: 'Group',
      type: NodeType.GROUP,
      icon: NODE_ICONS[NodeType.GROUP],
      color: '#ffffff',
    },
    {
      label: 'Note',
      type: NodeType.NOTE,
      icon: NODE_ICONS[NodeType.NOTE],
      color: NODE_COLORS[NodeType.NOTE],
    },
    // {
    //   label: 'Decision Table',
    //   type: NodeType.TABLE,
    //   icon: NODE_ICONS[NodeType.TABLE],
    //   color: NODE_COLORS[NodeType.TABLE],
    // },
  ];

  public get filteredBlocks(): FlowGraphBlock[] {
    return this.blocks.filter((block) =>
      block.label.toLowerCase().includes(this.searchTerm.toLowerCase())
    );
  }

  public onBlockClicked(type: NodeType): void {
    let data: any = null;

    if (type === NodeType.EDGE) {
      data = {
        source: null,
        then: null,
        python_code: {
          libraries: [],
          code: 'def main(arg1: str, arg2: str) -> dict:\n    return {\n        "result": arg1 + arg2,\n    }\n',
          entrypoint: 'main',
        },
      };
    } else if (type === NodeType.PYTHON) {
      data = {
        name: 'Python Code Node',
        libraries: [],
        code: 'def main(arg1: str, arg2: str) -> dict:\n    return {\n        "result": arg1 + arg2,\n    }\n',
        entrypoint: 'main',
      };
    } else if (type === NodeType.GROUP) {
      data = 'group'; // Assign "group" if NodeType is GROUP
    } else if (type === NodeType.TABLE) {
      // Provide mock data for a decision table node
      data = {
        name: 'Decision Table',
        table: {
          graph: null,
          condition_groups: [],
          node_name: '',
          default_next_node: null,
        },
      };
    } else if (type === NodeType.NOTE) {
      data = {
        content: 'Add your note here...',
        backgroundColor: NODE_COLORS[NodeType.NOTE],
      };
    }

    this.nodeSelected.emit({ type, data });
  }
}
