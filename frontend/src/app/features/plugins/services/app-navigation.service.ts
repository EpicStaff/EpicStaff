import { Location } from '@angular/common';
import { computed, inject, Injectable } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, UrlTree } from '@angular/router';
import { filter, map } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { AvailablePlugin } from '../models/available-plugin.model';
import { PLUGIN_PAGE_ROUTE_SEGMENT } from '../pages/plugin-host-page/plugin-page.matcher';
import { activeMenuItem, menuPathSegments, navigationContextOf } from '../utils/app-context.util';
import { AppReturnUrlService } from './app-return-url.service';
import { AvailablePluginsStorageService } from './available-plugins-storage.service';
import { SeenAppsService } from './seen-apps.service';

/** Where a SuperAdmin manages the installed plugins. */
export const MANAGE_APPS_URL = '/workspace/plugins';

/** An app menu entry, as the sidebar draws it. */
export interface AppMenuItem {
    readonly label: string;
    /** The manifest's path below the app, e.g. `/projects`. */
    readonly path: string;
    readonly iconUrl: string;
    /** Router commands to the item's page: `['/plugins', <identifier>, ...segments]`. */
    readonly link: string[];
}

/**
 * Everything the sidebar needs about apps: whether the address shows EpicStaff or an app, the apps the user may open
 * here, the open app's menu and the item the page belongs to, the way back to EpicStaff, and which apps are new.
 *
 * The context follows the address alone, so a plugin page that reports a new path (`nav.changed` moves the address)
 * moves the menu's highlight with it.
 */
@Injectable({ providedIn: 'root' })
export class AppNavigationService {
    // Declared ahead of the state, whose initializers read the address and the list through them.
    private readonly router = inject(Router);
    private readonly availablePlugins = inject(AvailablePluginsStorageService);

    /** The router URL, after every navigation. */
    private readonly url = toSignal(
        this.router.events.pipe(
            filter((event) => event instanceof NavigationEnd),
            map(() => this.router.url)
        ),
        { initialValue: this.router.url }
    );
    readonly context = computed(() => navigationContextOf(this.url()));
    /** Sorted by name. */
    readonly apps = this.availablePlugins.plugins;
    /** The app the address shows, when the user may open it here; else `null` (EpicStaff, or an app not in the list). */
    readonly currentApp = computed<AvailablePlugin | null>(() => {
        const context = this.context();
        if (context.kind !== 'app') return null;
        return this.apps().find((app) => app.identifier === context.identifier) ?? null;
    });
    /** The current app's menu, without the items whose path breaks the manifest's rule. */
    readonly menu = computed<AppMenuItem[]>(() => {
        const app = this.currentApp();
        return app ? toMenuItems(app) : [];
    });
    /** The menu item the page shown belongs to. */
    readonly activeMenuItem = computed<AppMenuItem | null>(() => {
        const context = this.context();
        return context.kind === 'app' ? activeMenuItem(this.menu(), context.pageSegments) : null;
    });
    /** Where "Back to EpicStaff" leads: the last EpicStaff page of this tab, its query included. */
    readonly returnUrl = computed<UrlTree>(() => this.router.parseUrl(this.appReturnUrl.url()));
    /** The address shown, for a plain link that opens it in a new tab. */
    readonly currentHref = computed(() => this.location.prepareExternalUrl(this.url()));
    readonly canManageApps = computed(
        () => this.configService.isPluginsEnabled && this.permissionsService.isSuperadmin
    );
    /** An app was granted since the user last opened an apps list. */
    readonly hasNewApps = computed(() => this.seenApps.newIdentifiers().size > 0);

    private readonly appReturnUrl = inject(AppReturnUrlService);
    private readonly seenApps = inject(SeenAppsService);
    private readonly configService = inject(ConfigService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly location = inject(Location);

    /**
     * An apps list opens: every app in it is seen from now on. Returns the apps that were new until now, so the list
     * can still tag them while it is open.
     */
    acknowledgeNewApps(): ReadonlySet<string> {
        const newIdentifiers = this.seenApps.newIdentifiers();
        this.seenApps.markSeen();
        return newIdentifiers;
    }
}

function toMenuItems(app: AvailablePlugin): AppMenuItem[] {
    return app.navigation.flatMap((item) => {
        const segments = menuPathSegments(item.path);
        // A blank label would leave a link without a name.
        if (segments === null || item.label.trim() === '') return [];
        return [
            {
                label: item.label,
                path: item.path,
                iconUrl: item.icon_url,
                link: [`/${PLUGIN_PAGE_ROUTE_SEGMENT}`, app.identifier, ...segments],
            },
        ];
    });
}
