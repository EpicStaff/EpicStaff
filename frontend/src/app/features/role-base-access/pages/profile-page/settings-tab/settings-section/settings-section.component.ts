import { Component, input } from '@angular/core';

/**
 * The frame of one settings section: its title, an optional one-line description, then the section's rows or editor,
 * all in the one column every section shares. A section can put its own buttons on the right of the header by
 * projecting an element marked `settingsSectionActions`.
 */
@Component({
    selector: 'app-settings-section',
    templateUrl: './settings-section.component.html',
    styleUrls: ['./settings-section.component.scss'],
})
export class SettingsSectionComponent {
    readonly heading = input.required<string>();
    readonly description = input<string>();
}
