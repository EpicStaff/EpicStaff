import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { getRelativeTime } from '@shared/utils';

@Component({
    selector: 'app-updated-at',
    imports: [DatePipe],
    templateUrl: './updated-at.component.html',
    styleUrls: ['./updated-at.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UpdatedAtComponent {
    readonly builtAt = input.required<string>();
    readonly nextBuildAt = input<string | null>(null);
    protected readonly builtAgo = computed(() => getRelativeTime(this.builtAt()));
}
