import { ChangeDetectionStrategy, Component, computed, input, model } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-audit-filter-group',
    standalone: true,
    imports: [AppSvgIconComponent],
    templateUrl: './audit-filter-group.component.html',
    styleUrls: ['./audit-filter-group.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditFilterGroupComponent {
    public label = input.required<string>();
    public hint = input<string>('');
    public disabled = input<boolean>(false);
    public expanded = model<boolean>(false);

    public isOpen = computed(() => this.expanded() && !this.disabled());

    public toggle(): void {
        if (this.disabled()) {
            return;
        }
        this.expanded.update((isExpanded) => !isExpanded);
    }
}
