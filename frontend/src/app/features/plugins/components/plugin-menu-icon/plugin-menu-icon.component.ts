import { Component, computed, input } from '@angular/core';

/**
 * The only sources a menu icon is drawn from: EpicStaff's public plugin files, or a package's icon inlined for review.
 * Neither can hold a quote, a parenthesis, a backslash or a space, so the source can't break out of its CSS `url()`.
 */
const ICON_SOURCE_PATTERN =
    /^(?:\/api\/plugin-public\/[A-Za-z0-9\-._~/?=&+%]+|data:image\/(?:svg\+xml|png);base64,[A-Za-z0-9+/]+={0,2})$/;

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
        return source !== null && ICON_SOURCE_PATTERN.test(source) ? `url("${source}")` : null;
    });
}
