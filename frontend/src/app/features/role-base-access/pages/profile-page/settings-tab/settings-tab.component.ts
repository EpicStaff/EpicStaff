import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { SideSectionNavComponent } from '@shared/components';

import { SETTINGS_SECTIONS } from './settings-sections';

/** The profile's Settings tab: a menu of sections on the left, the open section on the right. */
@Component({
    selector: 'app-settings-tab',
    templateUrl: './settings-tab.component.html',
    styleUrls: ['./settings-tab.component.scss'],
    imports: [RouterOutlet, SideSectionNavComponent],
})
export class SettingsTabComponent {
    protected readonly sections = SETTINGS_SECTIONS;
}
