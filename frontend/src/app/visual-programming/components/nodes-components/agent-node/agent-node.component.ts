import {
  Component,
  Input,
  ChangeDetectionStrategy,
  signal,
} from '@angular/core';
import {
  trigger,
  transition,
  style,
  animate,
  sequence,
} from '@angular/animations';
import { GetAgentRequest } from '../../../../shared/models/agent.model';
import { NgFor, NgIf, SlicePipe } from '@angular/common';
import { AgentNodeModel } from '../../../core/models/node.model';

@Component({
  selector: 'agent-node',
  standalone: true,
  templateUrl: './agent-node.component.html',
  styleUrls: ['./agent-node.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgIf, SlicePipe],
  animations: [
    trigger('expandCollapse', [
      transition(':enter', [
        // First, quickly expand the container height.
        sequence([
          style({ height: 0, opacity: 0 }),
          animate('100ms ease-out', style({ height: '*' })),
          // Then fade in the content.
          animate('150ms ease-out', style({ opacity: 1 })),
        ]),
      ]),
      transition(':leave', [
        sequence([
          // Fade out the content first.
          animate('100ms ease-in', style({ opacity: 0 })),
          // Then collapse the container.
          animate('150ms ease-in', style({ height: 0 })),
        ]),
      ]),
    ]),
  ],
})
export class AgentNodeComponent {
  @Input() public node!: AgentNodeModel;
  @Input() public parentExpanded = signal(false);
  public isGoalExpanded = signal(false);
  public isBackstoryExpanded = signal(false);

  public toggleGoal(event: MouseEvent): void {
    event.stopPropagation();
    this.isGoalExpanded.set(!this.isGoalExpanded());
  }

  public toggleBackstory(event: MouseEvent): void {
    event.stopPropagation();
    this.isBackstoryExpanded.set(!this.isBackstoryExpanded());
  }
}
