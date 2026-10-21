import { DOCUMENT } from '@angular/common';
import { inject, Injectable } from '@angular/core';

/**
 * Leaves EpicStaff's page for the authorize request a plugin sign-in continues with. Always `location.replace`, never
 * `assign` or a router navigation: the page may be inside a plugin's frame, where any new history entry lands in
 * EpicStaff's own history, so Back would step through the sign-in instead of leaving the plugin.
 */
@Injectable({ providedIn: 'root' })
export class PluginLoginNavigationService {
    private readonly document = inject(DOCUMENT);

    /** Goes to `path` (a checked `continue`) on this page's own origin, and nowhere else. */
    continueTo(path: string): void {
        const location = this.document.location;
        const target = new URL(path, location.origin);
        if (target.origin !== location.origin) return;
        location.replace(target.href);
    }
}
