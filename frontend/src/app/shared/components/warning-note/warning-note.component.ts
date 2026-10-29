import { Component } from '@angular/core';

/**
 * The system warning bar (the validation errors' bar in warning colours): a short line under a field
 * saying something kept there doesn't work, e.g. a pick that is in the recycle bin. The text is projected.
 */
@Component({
    selector: 'app-warning-note',
    template: '<ng-content />',
    styleUrls: ['./warning-note.component.scss'],
})
export class WarningNoteComponent {}
