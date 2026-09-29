import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
    selector: 'app-list-column',
    changeDetection: ChangeDetectionStrategy.Eager,
    template: `
        <div
            class="list__column"
            [style.width]="width()"
        >
            <ng-content />
        </div>
    `,
})
export class ListColumnComponent {
    width = input<string | null>(null);
}
