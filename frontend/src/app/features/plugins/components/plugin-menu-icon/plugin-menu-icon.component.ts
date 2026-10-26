import { Component, computed, input } from '@angular/core';

import { PLUGIN_IDENTIFIER_PATTERN } from '../../utils/plugin-frame-url.util';

/**
 * A menu icon as the server links it: `/api/plugin-public/<identifier>/icons/<file>/?v=<version>`. Each part is then
 * held to the manifest's own rule, so no part can be a dot segment or a `%` escape, which the browser would resolve to
 * another path of this site before fetching it.
 */
const MENU_ICON_URL_PATTERN = /^\/api\/plugin-public\/([^/]+)\/icons\/([^/]+)\/\?v=([^&#]+)$/;
/** The manifest's menu icon file, without its `icons/` folder. */
const MENU_ICON_FILE_PATTERN = /^[a-z0-9][a-z0-9_-]{0,62}\.(?:svg|png)$/;
/** The manifest's version: SemVer 2.0 with ASCII digits only. */
const VERSION_PATTERN =
    /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*)?(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$/;
/** A package's menu icon inlined for review. */
const REVIEW_ICON_DATA_URL_PATTERN = /^data:image\/(?:svg\+xml|png);base64,[A-Za-z0-9+/]+={0,2}$/;

/**
 * The only sources a menu icon is drawn from: a plugin's menu icon file, or a package's icon inlined for review.
 * Neither can hold a quote, a parenthesis, a backslash or a space, so the source can't break out of its CSS `url()`.
 */
function isMenuIconSource(source: string): boolean {
    if (REVIEW_ICON_DATA_URL_PATTERN.test(source)) return true;
    const parts = MENU_ICON_URL_PATTERN.exec(source);
    if (parts === null) return false;
    const [, identifier, file, version] = parts;
    return (
        PLUGIN_IDENTIFIER_PATTERN.test(identifier) && MENU_ICON_FILE_PATTERN.test(file) && VERSION_PATTERN.test(version)
    );
}

/**
 * An icon from a plugin's app menu, drawn as a CSS mask in the text colour around it, so it follows the theme and
 * the row's hover and active colours like the sprite icons do. Only the icon's shape counts: a multi-colour icon
 * becomes a one-colour shape. A source from anywhere else is not loaded; a dot stands in for it.
 */
@Component({
    selector: 'app-plugin-menu-icon',
    templateUrl: './plugin-menu-icon.component.html',
    styleUrl: './plugin-menu-icon.component.scss',
    host: {
        'aria-hidden': 'true',
        '[class.plugin-menu-icon--drawn]': 'maskImage() !== null',
        '[style.--plugin-menu-icon-size]': 'size()',
        '[style.mask-image]': 'maskImage()',
    },
})
export class PluginMenuIconComponent {
    readonly src = input<string | null>(null);
    /** A CSS length. */
    readonly size = input('1.25rem');

    protected readonly maskImage = computed(() => {
        const source = this.src();
        return source !== null && isMenuIconSource(source) ? `url("${source}")` : null;
    });
}
