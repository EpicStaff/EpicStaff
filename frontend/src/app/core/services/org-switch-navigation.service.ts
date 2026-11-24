import { inject, Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { ORG_SWITCH_URL_RULES } from '@shared/services';

/** Re-enters the current page, so its guards run again and it reloads its data for the current access and org. */
@Injectable({ providedIn: 'root' })
export class OrgSwitchNavigationService {
    private readonly router = inject(Router);
    /** Features' own rules for their addresses (a plugin page keeps the plugin, not its path). */
    private readonly orgSwitchUrlRules = inject(ORG_SWITCH_URL_RULES, { optional: true }) ?? [];

    /** Re-enters the current address, for a page whose access may have changed within the same org. */
    reenterCurrentPage(): void {
        this.reenter(this.router.url);
    }

    /**
     * Re-enters the page after the active org changed, at the address the new org can open (`urlForOrgSwitch`)
     * rather than at a resource of the previous org.
     */
    reenterAfterOrgSwitch(): void {
        this.reenter(this.urlForOrgSwitch(this.router.url));
    }

    /** Leaves the page for `/profile` without touching the address bar, then goes to `targetUrl`. */
    private reenter(targetUrl: string): void {
        void this.router.navigateByUrl('/profile', { skipLocationChange: true }).then(() => {
            void this.router.navigateByUrl(targetUrl);
        });
    }

    /**
     * Detail routes with resource IDs are not safe to keep across an org switch —
     * the resource may not exist in the new org. Map them to their list page.
     * Other features map their own addresses through `ORG_SWITCH_URL_RULES` (a plugin page keeps the plugin but drops
     * its own path; the plugin page guard sends the user to the default route when the new org can't open it).
     */
    private urlForOrgSwitch(currentUrl: string): string {
        if (/^\/flows\/(?!my|templates)[^/?]+/.test(currentUrl)) return '/flows/my';
        if (/^\/graph\//.test(currentUrl)) return '/sessions';
        for (const rule of this.orgSwitchUrlRules) {
            const mapped = rule(currentUrl);
            if (mapped !== null) return mapped;
        }
        return currentUrl;
    }
}
