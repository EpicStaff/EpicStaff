import {
  Component,
  Input,
  ChangeDetectionStrategy,
  signal,
} from '@angular/core';
import { NgIf, SlicePipe } from '@angular/common';
import { TaskNodeModel } from '../../../core/models/node.model';

@Component({
  selector: 'task-node',
  templateUrl: './task-node.component.html',
  styleUrls: ['./task-node.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: true,
  imports: [NgIf, SlicePipe],
})
export class TaskNodeComponent {
  @Input() node!: TaskNodeModel;

  // Receive the parent's expanded signal to control the display of details.
  @Input() parentExpanded = signal(false);

  // Convert local toggling states to signals.
  public isInstructionsExpanded = signal(false);
  public isExpectedOutputExpanded = signal(false);

  public toggleInstructions(event: MouseEvent): void {
    event.stopPropagation();
    this.isInstructionsExpanded.set(!this.isInstructionsExpanded());
  }

  public toggleExpectedOutput(event: MouseEvent): void {
    event.stopPropagation();
    this.isExpectedOutputExpanded.set(!this.isExpectedOutputExpanded());
  }
}
