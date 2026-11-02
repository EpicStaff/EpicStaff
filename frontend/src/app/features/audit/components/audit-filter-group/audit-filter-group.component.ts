import { ChangeDetectionStrategy, Component, computed, input, model, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';

@Component({
    selector: 'app-audit-filter-group',
    standalone: true,
    imports: [AppSvgIconComponent, MatTooltipModule, TooltipOnOverflowDirective],
    templateUrl: './audit-filter-group.component.html',
    styleUrls: ['./audit-filter-group.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditFilterGroupComponent {
    public label = input.required<string>();
    public hint = input<string>('');
    public disabled = input<boolean>(false);
    // the applied value, shown on the collapsed card next to a button that clears it
    public summary = input<string>('');
    public expanded = model<boolean>(false);
    public readonly cleared = output<void>();

    public isOpen = computed(() => this.expanded() && !this.disabled());

    public toggle(): void {
        if (this.disabled()) {
            return;
        }
        this.expanded.update((isExpanded) => !isExpanded);
    }
}
