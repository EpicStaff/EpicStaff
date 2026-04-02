import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { AppIconComponent } from '../../../../../../../shared/components/app-icon/app-icon.component';

@Component({
    selector: 'app-file-preview',
    templateUrl: './file-preview.component.html',
    styleUrls: ['./file-preview.component.scss'],
    imports: [AppIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FilePreviewComponent {
    file = input<File | null>(null);
}
