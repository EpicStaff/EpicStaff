import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormsModule } from '@angular/forms';
import { HelpTooltipComponent } from '../../../../../shared/components/help-tooltip/help-tooltip.component';

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
  @Input() collectionName!: string;
  @Output() fileUploaded = new EventEmitter<File>();

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.fileUploaded.emit(input.files[0]);
    }
  }
}
