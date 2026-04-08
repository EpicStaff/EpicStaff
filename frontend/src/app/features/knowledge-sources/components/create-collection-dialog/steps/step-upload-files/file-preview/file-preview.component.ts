import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-file-preview',
    templateUrl: './file-preview.component.html',
    styleUrls: ['./file-preview.component.scss'],
    imports: [AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FilePreviewComponent {
    file = input<File | null>(null);
}
