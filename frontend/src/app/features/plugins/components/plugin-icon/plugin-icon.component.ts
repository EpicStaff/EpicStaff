import { Component, input } from '@angular/core';

/**
 * A plugin's icon. Always a plain `<img>`, never inlined: an SVG shown as an image runs no script and loads nothing.
 * Without a source (a plugin not approved yet) it shows a generic puzzle piece.
 */
@Component({
    selector: 'app-plugin-icon',
    templateUrl: './plugin-icon.component.html',
    styleUrl: './plugin-icon.component.scss',
    host: { '[style.--plugin-icon-size]': 'size()' },
})
export class PluginIconComponent {
    readonly src = input<string | null>(null);
    /** The image's text alternative; empty when a label next to it names the plugin already. */
    readonly alt = input('');
    /** A CSS length. */
    readonly size = input('24px');
}
