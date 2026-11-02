import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    input,
    model,
    output,
    viewChild,
} from '@angular/core';
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

    private readonly header = viewChild.required<ElementRef<HTMLButtonElement>>('header');

    public isOpen = computed(() => this.expanded() && !this.disabled());

    public toggle(): void {
        if (this.disabled()) {
            return;
        }
        this.expanded.update((isExpanded) => !isExpanded);
    }

    // the clear button goes with the summary it clears, so the focus moves to the group's header
    public clear(): void {
        this.cleared.emit();
        this.header().nativeElement.focus();
    }
}
