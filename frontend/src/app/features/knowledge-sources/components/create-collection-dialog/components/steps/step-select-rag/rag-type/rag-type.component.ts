import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { Rag } from '../../../../../../models/base-rag.model';

@Component({
    selector: 'app-rag-type',
    templateUrl: './rag-type.component.html',
    styleUrls: ['./rag-type.component.scss'],
    imports: [AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RagTypeComponent {
    rag = input.required<Rag>();
    selected = input<boolean>(false);
}
