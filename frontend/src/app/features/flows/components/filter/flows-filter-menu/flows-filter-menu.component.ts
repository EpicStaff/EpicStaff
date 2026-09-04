import { ChangeDetectionStrategy, Component, output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';

export type FlowsFilterMenuAction = 'sort_asc' | 'sort_desc' | 'include_exclude' | 'custom_filter';

@Component({
    selector: 'app-flows-filter-menu',
    imports: [AppSvgIconComponent],
    templateUrl: './flows-filter-menu.component.html',
    styleUrls: ['./flows-filter-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsFilterMenuComponent {
    public readonly actionSelected = output<FlowsFilterMenuAction>();

    public onSelect(action: FlowsFilterMenuAction): void {
        this.actionSelected.emit(action);
    }
}
