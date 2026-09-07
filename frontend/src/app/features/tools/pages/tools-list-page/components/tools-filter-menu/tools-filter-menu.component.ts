import { ChangeDetectionStrategy, Component, output } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

export type ToolsFilterMenuAction =
    | 'show_favorite'
    | 'sort_asc'
    | 'sort_desc'
    | 'used_in_projects'
    | 'used_in_agents'
    | 'most_used'
    | 'unused_first'
    | 'include_exclude'
    | 'custom_filter';

@Component({
    selector: 'app-tools-filter-menu',
    imports: [AppSvgIconComponent],
    templateUrl: './tools-filter-menu.component.html',
    styleUrls: ['./tools-filter-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsFilterMenuComponent {
    public readonly actionSelected = output<ToolsFilterMenuAction>();

    public onSelect(action: ToolsFilterMenuAction): void {
        this.actionSelected.emit(action);
    }
}
