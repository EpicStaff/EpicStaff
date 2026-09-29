import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export interface EntityFieldEntry {
    label: string;
    value: string;
}

@Component({
    selector: 'app-entity-fields-list',
    templateUrl: './entity-fields-list.component.html',
    styleUrls: ['./entity-fields-list.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EntityFieldsListComponent {
    public readonly fields = input.required<EntityFieldEntry[]>();
    public readonly expanded = input<boolean>(false);
}
