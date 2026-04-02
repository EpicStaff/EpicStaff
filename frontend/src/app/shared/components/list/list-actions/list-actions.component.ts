import { Component } from '@angular/core';

@Component({
    selector: 'app-list-actions',
    template: `
        <div class="list-actions">
            <ng-content />
        </div>
    `,
    styleUrls: ['./list-actions.component.scss'],
})
export class ListActionsComponent {}
