import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
} from '@angular/core';
import {
  FormBuilder,
  FormGroup,
  FormControl,
  Validators,
  FormsModule,
  ReactiveFormsModule,
} from '@angular/forms';
import { CommonModule } from '@angular/common';
import { ToolsService } from '../../../../features/tools/services/tools.service';
import { Tool, ToolField } from '../../../../features/tools/models/tool.model';
// Import the specific node model for tool nodes.
import { ToolNodeModel } from '../../../core/models/node.model';

@Component({
  selector: 'app-tool-config-side-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule],
  templateUrl: './tool-config-edit-dialog.component.html',
  styleUrls: ['./tool-config-edit-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolConfigSidePanelComponent implements OnInit {
  // Standardize the input as "node" for consistency.
  @Input() node!: ToolNodeModel;
  @Output() closePanel = new EventEmitter<void>();
  @Output() nodeUpdated = new EventEmitter<ToolNodeModel>();

  public toolConfigForm!: FormGroup;
  public tool!: Tool;
  public loading = true;
  public error: string | null = null;

  constructor(
    private fb: FormBuilder,
    private toolService: ToolsService,
    private changeDetectorRef: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    // Use node.data.tool (the tool ID) to fetch the related tool.
    // this.toolService.getToolById(this.node.data.tool).subscribe({
    //   next: (tool) => {
    //     this.tool = tool;
    //     this.initializeForm();
    //     this.loading = false;
    //     this.changeDetectorRef.markForCheck();
    //   },
    //   error: (err) => {
    //     this.error = 'Error fetching tool details.';
    //     this.loading = false;
    //     this.changeDetectorRef.markForCheck();
    //   },
    // });
  }

  /**
   * Build the form dynamically. In addition to the "name", "tool", and "is_completed" fields,
   * create a nested form group "configuration" with one control per tool field.
   */
  initializeForm(): void {
    const configGroup: { [key: string]: FormControl } = {};

    this.tool.tool_fields.forEach((field: ToolField) => {
      // Retrieve the current value from node.data.configuration (if any)
      const value =
        this.node.data.configuration &&
        this.node.data.configuration[field.name] !== undefined
          ? this.node.data.configuration[field.name]
          : null;

      // Set a default value; for booleans, default to false.
      let defaultValue = value;
      if (
        field.data_type === 'boolean' &&
        (value === null || value === undefined)
      ) {
        defaultValue = false;
      }
      if (defaultValue === null) {
        defaultValue = '';
      }

      // Prepare validators. Add Validators.required if the field is required.
      const validators = [];
      if (field.required) {
        validators.push(Validators.required);
      }
      // For integers, add a pattern validator to allow negative numbers.
      if (field.data_type === 'integer') {
        validators.push(Validators.pattern(/^-?\d+$/));
      }

      configGroup[field.name] = new FormControl(defaultValue, validators);
    });

    this.toolConfigForm = this.fb.group({
      name: [this.node.data.name, Validators.required],
      // Tool id is displayed as read-only; we show the tool name in the template.
      tool: [{ value: this.node.data.tool, disabled: true }],
      is_completed: [this.node.data.is_completed],
      configuration: this.fb.group(configGroup),
    });
  }

  onSubmit(): void {
    if (this.toolConfigForm.valid) {
      // Merge updated fields into node.data only, preserving base node properties.
      const updatedToolConfig = {
        ...this.node.data,
        ...this.toolConfigForm.getRawValue(),
      };

      const updatedNode: ToolNodeModel = {
        ...this.node,
        data: updatedToolConfig,
      };

      this.nodeUpdated.emit(updatedNode);
      this.close();
    }
  }

  close(): void {
    this.closePanel.emit();
  }
}
