import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

export interface DetailCrumb {
    label: string;
    navAgentId?: number;
    navAgentSurfacesId?: number;
}

@Component({
    selector: 'app-detail-header',
    imports: [AppSvgIconComponent],
    templateUrl: './detail-header.component.html',
    styleUrls: ['./detail-header.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DetailHeaderComponent {
    showSidebar = input<boolean>(true);
    crumbs = input<DetailCrumb[]>([]);

    readonly toggleSidebar = output<void>();
    readonly navAgent = output<number>();
    readonly navAgentSurfaces = output<number>();
}
