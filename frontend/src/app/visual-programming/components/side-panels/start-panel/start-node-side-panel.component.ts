import {
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
  inject,
} from '@angular/core';
import {
  FormBuilder,
  FormGroup,
  FormsModule,
  ReactiveFormsModule,
} from '@angular/forms';
import { NgIf } from '@angular/common';

import { StartNodeModel } from '../../../core/models/node.model';
import { FlowService } from '../../../services/flow.service';
import { JsonEditorComponent } from '../../../../shared/components/json-editor/json-editor.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';

@Component({
  selector: 'app-start-node-side-panel',
  standalone: true,
  templateUrl: './start-node-side-panel.component.html',
  styleUrls: ['./start-node-side-panel.component.scss'],
  imports: [
    FormsModule,
    ReactiveFormsModule,
    JsonEditorComponent,

    HelpTooltipComponent,
  ],
})
export class StartNodeSidePanelComponent implements OnInit {
  @Input() node!: StartNodeModel;
  @Output() closePanel = new EventEmitter<void>();
  @Output() nodeUpdated = new EventEmitter<StartNodeModel>();

  public nodeForm!: FormGroup;
  public initialStateJson: string = '{}';
  public isJsonValid: boolean = true;

  private fb = inject(FormBuilder);
  private flowService = inject(FlowService);

  ngOnInit(): void {
    // Initialize the form - no longer has node_name field
    this.nodeForm = this.fb.group({});

    // Initialize the JSON editor with existing data or default empty object
    if (this.node?.data?.initialState) {
      try {
        // If it's already a string, use it directly
        if (typeof this.node.data.initialState === 'string') {
          this.initialStateJson = this.node.data.initialState;
        } else {
          // Otherwise stringify the object
          this.initialStateJson = JSON.stringify(
            this.node.data.initialState,
            null,
            2
          );
        }
      } catch (e) {
        console.error('Error parsing initial state JSON:', e);
        this.initialStateJson = '{}';
      }
    }
  }

  onJsonValidChange(isValid: boolean): void {
    this.isJsonValid = isValid;
  }

  onSubmit(): void {
    if (this.isJsonValid) {
      // Parse the JSON for initialState
      let initialState = {};
      try {
        initialState = JSON.parse(this.initialStateJson);
      } catch (e) {
        console.error('Error parsing JSON:', e);
        return; // Don't submit if JSON is invalid
      }

      const updatedNode: StartNodeModel = {
        ...this.node,
        // Keep the original node_name - no changes allowed
        data: {
          ...this.node.data,
          initialState: initialState,
        },
      };

      // Preserve the existing output_variable_path
      if (this.node.output_variable_path !== undefined) {
        updatedNode.output_variable_path = this.node.output_variable_path;
      }

      this.nodeUpdated.emit(updatedNode);
      this.close();
    }
  }

  close(): void {
    this.closePanel.emit();
  }
}
