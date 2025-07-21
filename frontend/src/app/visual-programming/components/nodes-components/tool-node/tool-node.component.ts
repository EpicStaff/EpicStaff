import { Component, Input, signal } from '@angular/core';

import { ToolConfig } from '../../../../features/tools/models/tool_config.model';
import { KeyValuePipe, NgFor, NgIf, TitleCasePipe } from '@angular/common';
import { ToolNodeModel } from '../../../core/models/node.model';

@Component({
  selector: 'app-tool-node',
  imports: [],
  standalone: true,
  templateUrl: './tool-node.component.html',
  styleUrl: './tool-node.component.scss',
})
export class ToolNodeComponent {
  @Input() node!: ToolNodeModel;

  // Receive the parent's expanded signal to control the display of details.
  //   @Input() parentExpanded = signal(false);
}
