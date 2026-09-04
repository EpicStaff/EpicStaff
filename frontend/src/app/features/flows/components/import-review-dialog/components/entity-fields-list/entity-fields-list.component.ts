import { animate, state, style, transition, trigger } from '@angular/animations';
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
    animations: [
        trigger('collapseExpand', [
            state('expanded', style({ height: '*', opacity: 1, overflow: 'hidden' })),
            state('collapsed', style({ height: '0', opacity: 0, overflow: 'hidden' })),
            transition('expanded <=> collapsed', animate('220ms ease')),
        ]),
    ],
})
export class EntityFieldsListComponent {
    public readonly fields = input.required<EntityFieldEntry[]>();
    public readonly expanded = input<boolean>(false);
}
