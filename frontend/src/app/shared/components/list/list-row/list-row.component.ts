import { ChangeDetectionStrategy, Component, HostBinding, signal } from '@angular/core';

@Component({
    selector: 'app-list-row',
    template: `<ng-content />`,

    styleUrls: ['./list-row.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ListRowComponent {
    selected = signal<boolean>(false);

    @HostBinding('class.list__row--selected')
    get selectedClass() {
        return this.selected();
    }
}
