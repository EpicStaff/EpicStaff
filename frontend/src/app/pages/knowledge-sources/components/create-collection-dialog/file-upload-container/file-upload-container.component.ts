import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormArray,
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
  FormsModule,
} from '@angular/forms';
import { ChunkStrategy } from '../../../models/source-collection.model';
import { chunkSizeGreaterThanOverlapValidator } from '../../../../../shared/form-validators/chunk-size.validator';
import { HelpTooltipComponent } from '../../../../../shared/components/help-tooltip/help-tooltip.component';

// Interface to track file settings
export interface FileWithSettings {
  file: File;
  chunkStrategy: ChunkStrategy;
  chunkSize: number;
  overlapSize: number;
  isValid: boolean; // Track file validity
  hasChunkSizeError?: boolean; // Track chunk size validation
}

@Component({
  selector: 'app-file-upload-container',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    FormsModule,
    HelpTooltipComponent,
  ],
  templateUrl: './file-upload-container.component.html',
  styleUrls: ['./file-upload-container.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FileUploadContainerComponent {
  @Input() fileSettingsFormArray!: FormArray;
  @Input() maxChunkSize: number = 8000;
  @Input() maxOverlapSize: number = 1000;
  @Input() chunkStrategies: { label: string; value: ChunkStrategy }[] = [
    { label: 'Token', value: 'token' },
    { label: 'Character', value: 'character' },
    { label: 'Markdown', value: 'markdown' },
    { label: 'JSON', value: 'json' },
    { label: 'HTML', value: 'html' },
  ];

  @Output() hasInvalidFilesChange = new EventEmitter<boolean>();

  filesWithSettings: FileWithSettings[] = [];
  isDragging = false;
  hasInvalidFiles = false;

  // Default values
  defaultChunkSize = 1000;
  defaultOverlapSize = 200;
  defaultChunkStrategy: ChunkStrategy = 'token';

  // Allowed file types
  allowedFileTypes = ['pdf', 'csv', 'docx', 'txt', 'json', 'html'];

  public additionalParamsInput: string = '{}';
  public hasAdditionalParamsError: boolean = false;

  constructor(private fb: FormBuilder) {}

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = true;
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = false;
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = false;

    if (event.dataTransfer?.files) {
      this.handleFiles(event.dataTransfer.files);
    }
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files) {
      this.handleFiles(input.files);
    }
  }

  handleFiles(fileList: FileList): void {
    Array.from(fileList).forEach((file) => {
      // Check if file already exists in the list by name and size
      const existingFileIndex = this.filesWithSettings.findIndex(
        (f) => f.file.name === file.name && f.file.size === file.size
      );

      if (existingFileIndex === -1) {
        // Check if file type is valid
        const isValid = this.isValidFileType(file);

        // Add to our tracked array of files with settings
        this.filesWithSettings.push({
          file,
          chunkStrategy: this.defaultChunkStrategy,
          chunkSize: this.defaultChunkSize,
          overlapSize: this.defaultOverlapSize,
          isValid: isValid,
          hasChunkSizeError: false,
        });

        // Add a corresponding form group to the form array
        this.fileSettingsFormArray.push(
          this.createFileSettingsGroup(file, isValid)
        );
      }
    });

    // Update invalid files status
    this.checkForInvalidFiles();

    console.log('Files Added:', this.filesWithSettings);
  }

  createFileSettingsGroup(file: File, isValid: boolean): FormGroup {
    const group = this.fb.group(
      {
        fileName: [file.name],
        fileSize: [file.size],
        isValid: [isValid],
        chunkStrategy: [this.defaultChunkStrategy, [Validators.required]],
        chunkSize: [
          this.defaultChunkSize,
          [
            Validators.required,
            Validators.min(1),
            Validators.max(this.maxChunkSize),
          ],
        ],
        overlapSize: [
          this.defaultOverlapSize,
          [
            Validators.required,
            Validators.min(0),
            Validators.max(this.maxOverlapSize),
          ],
        ],
      },
      { validators: chunkSizeGreaterThanOverlapValidator() }
    );

    return group;
  }

  // Helper method to check if file type is allowed
  isValidFileType(file: File): boolean {
    const extension = file.name.split('.').pop()?.toLowerCase() || '';
    return this.allowedFileTypes.includes(extension);
  }

  // Check if a file setting has a chunk size error
  hasChunkError(index: number): boolean {
    const group = this.fileSettingsFormArray.at(index);
    return group ? group.hasError('chunkSizeTooSmall') : false;
  }

  // Check if any files are invalid
  checkForInvalidFiles(): void {
    // Check for invalid file types
    const hasInvalidTypes = this.filesWithSettings.some(
      (file) => !file.isValid
    );

    // Check for chunk size validation errors
    const hasChunkErrors = this.fileSettingsFormArray.controls.some((control) =>
      control.hasError('chunkSizeTooSmall')
    );

    // Update the hasInvalidFiles flag
    this.hasInvalidFiles = hasInvalidTypes || hasChunkErrors;

    // Also update the hasChunkSizeError flag on each file
    this.filesWithSettings.forEach((file, index) => {
      file.hasChunkSizeError = this.hasChunkError(index);
    });

    // Emit the change
    this.hasInvalidFilesChange.emit(this.hasInvalidFiles);
  }

  removeFile(index: number): void {
    this.filesWithSettings.splice(index, 1);
    this.fileSettingsFormArray.removeAt(index);

    // Update invalid files status after removal
    this.checkForInvalidFiles();

    console.log('Remaining Files:', this.filesWithSettings);
  }

  updateFileSettings(index: number, field: string, value: any): void {
    const numericValue =
      field !== 'chunkStrategy' ? parseInt(value, 10) : value;

    // Update our tracked array
    if (field === 'chunkStrategy') {
      this.filesWithSettings[index].chunkStrategy = value;
    } else if (field === 'chunkSize') {
      this.filesWithSettings[index].chunkSize = numericValue;
    } else if (field === 'overlapSize') {
      this.filesWithSettings[index].overlapSize = numericValue;
    }

    // Update the form control
    const control = this.fileSettingsFormArray.at(index);
    control.get(field)?.setValue(numericValue);

    // Run validation after the update
    control.updateValueAndValidity();

    // Update the file's error state
    this.filesWithSettings[index].hasChunkSizeError = this.hasChunkError(index);

    // Update overall invalid status
    this.checkForInvalidFiles();
  }

  // Method to get files for form submission
  getFiles(): FileWithSettings[] {
    return this.filesWithSettings;
  }

  public getAdditionalParams(): any {
    try {
      this.hasAdditionalParamsError = false;
      return this.additionalParamsInput
        ? JSON.parse(this.additionalParamsInput)
        : {};
    } catch {
      this.hasAdditionalParamsError = true;
      return {};
    }
  }
}
