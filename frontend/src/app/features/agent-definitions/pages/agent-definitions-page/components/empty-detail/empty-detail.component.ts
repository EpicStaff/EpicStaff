import { ChangeDetectionStrategy, Component } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-empty-detail',
    imports: [AppSvgIconComponent],
    templateUrl: './empty-detail.component.html',
    styleUrls: ['./empty-detail.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EmptyDetailComponent {}
