import {
  ChangeDetectionStrategy,
  Component,
  Input,
  Output,
  EventEmitter,
} from '@angular/core';
import { NgFor } from '@angular/common';
import { NodeType } from '../../../core/enums/node-type';

interface ProjectGraphBlock {
  label: string;
  icon: string;
  type:
    | NodeType
    | 'group'
    | 'PROMPT_NODE'
    | 'KNOWLEDGE_NODE'
    | 'VARIABLES_NODE'
    | 'MEMORY_NODE'
    | 'FUNCTION_NODE'
    | 'CUSTOM_TRIGGER_NODE';
  color: string;
}

@Component({
  selector: 'app-project-graph-core-menu',
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
      }
      li {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 16px;
        border-radius: 8px;
        gap: 16px;
        cursor: pointer;
        transition: background 0.2s ease;
        position: relative;
      }
      li:hover {
        background: #2a2a2a;
      }
      li i {
        font-size: 16px;
        color: #bbb;
        transition: color 0.2s ease;
      }
      li:hover i {
        color: inherit; /* Keep the color assigned from the template */
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
        color: inherit; /* Keep the assigned block color */
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgFor],
})
export class ProjectGraphCoreMenuComponent {
  @Input() public searchTerm: string = '';

  /**
   * Just like FlowGraphCoreMenuComponent, we emit { type, data } instead of a block object.
   */
  @Output() public nodeSelected = new EventEmitter<{
    type: NodeType;
    data: any;
  }>();

  /**
   * Notice we define 'type' for each block.
   * You can modify or expand the list based on your application logic.
   */
  public blocks: ProjectGraphBlock[] = [
    {
      label: 'Task',
      icon: 'ti ti-list',
      type: NodeType.TASK,
      color: '#30a46c',
    },
    // { label: 'Group', icon: 'ti ti-users', type: 'group', color: '#2a6bbf' },
    {
      label: 'Prompt Node',
      icon: 'ti ti-message',
      type: 'PROMPT_NODE',
      color: '#a855f7',
    },
    {
      label: 'Knowledge Node',
      icon: 'ti ti-book',
      type: 'KNOWLEDGE_NODE',
      color: '#facc15',
    },
    {
      label: 'Variables Node',
      icon: 'ti ti-variable',
      type: 'VARIABLES_NODE',
      color: '#f97316',
    },
    {
      label: 'Memory Node',
      icon: 'ti ti-brain',
      type: 'MEMORY_NODE',
      color: '#e11d48',
    },
    {
      label: 'Function Node',
      icon: 'ti ti-function',
      type: 'FUNCTION_NODE',
      color: '#3b82f6',
    },
    {
      label: 'Custom Trigger Node',
      icon: 'ti ti-bolt',
      type: 'CUSTOM_TRIGGER_NODE',
      color: '#9333ea',
    },
  ];

  /**
   * Filter the blocks based on the search term.
   */
  public get filteredBlocks(): ProjectGraphBlock[] {
    return this.blocks.filter((block) =>
      block.label.toLowerCase().includes(this.searchTerm.toLowerCase())
    );
  }

  /**
   * Using the same pattern: We build a 'data' object
   * depending on the 'type' and then emit { type, data }.
   */
  public onBlockClicked(type: NodeType | string): void {
    console.log('Block clicked with type:', type); // Add this line to see what type is passed

    let data: any = null;

    if (type === NodeType.TASK) {
      data = {
        name: 'New Task',
        instructions: '',
        expected_output: '',
        order: null,
        human_input: false,
        async_execution: false,
        config: null,
        output_model: null,
        crew: null,
        agent: null,
      };
      console.log('task node emitted');
    } else if (type === NodeType.GROUP) {
      data = 'group'; // Assign "group" if NodeType is GROUP
    } else {
      return;
    }

    // ✅ Explicitly cast `type` to match the EventEmitter's expected type
    this.nodeSelected.emit({ type, data });
  }
}
