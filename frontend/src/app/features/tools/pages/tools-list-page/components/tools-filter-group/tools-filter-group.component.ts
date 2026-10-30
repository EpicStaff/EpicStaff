import { ChangeDetectionStrategy, Component, computed, input, model, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-tools-filter-group',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './tools-filter-group.component.html',
    styleUrls: ['./tools-filter-group.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsFilterGroupComponent {
    public readonly label = input.required<string>();
    public readonly hint = input<string>('');
    public readonly disabled = input<boolean>(false);
    public readonly summary = input<string>('');
    public readonly expanded = model<boolean>(false);
    public readonly cleared = output<void>();

    protected readonly isOpen = computed(() => this.expanded() && !this.disabled());

    protected toggle(): void {
        if (this.disabled()) {
            return;
        }
        this.expanded.update((isExpanded) => !isExpanded);
    }
}
