import { Component, input } from '@angular/core';

import { PluginBadgeTone } from '../../utils/plugin-display.util';

/** A short status label: a plugin's state, its trust, a grant's state. */
@Component({
    selector: 'app-plugin-badge',
    template:
        '<span class="plugin-badge text-body-small-large" [class]="\'plugin-badge--\' + tone()">{{ label() }}</span>',
    styleUrl: './plugin-badge.component.scss',
})
export class PluginBadgeComponent {
    readonly label = input.required<string>();
    readonly tone = input<PluginBadgeTone>('neutral');
}
