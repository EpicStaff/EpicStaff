import { DOCUMENT } from '@angular/common';
import { computed, inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { navigationContextOf } from '../utils/app-context.util';

/** `sessionStorage`: one per browser tab, so two tabs return to their own pages. */
const RETURN_URL_KEY = 'epicstaff.appReturnUrl';

/**
 * Where "Back to EpicStaff" leads from an app: the last EpicStaff page shown in this tab (the main layout records every
 * one), else the signed-in user's default page.
 *
 * Kept in `sessionStorage`, so a reload inside an app still knows the way back. Registered in `APP_STORAGE`: an
 * organization switch or a logout forgets it, as the page may not exist for the next organization or user.
 */
@Injectable({ providedIn: 'root' })
export class AppReturnUrlService implements StorageService {
    // Declared ahead of the state, whose initializer reads the stored URL through it.
    private readonly document = inject(DOCUMENT);

    private readonly recordedUrl = signal<string | null>(this.readStored());
    readonly url = computed(() => this.recordedUrl() ?? this.permissionsService.resolveDefaultRoute());

    private readonly permissionsService = inject(PermissionsService);

    /** Remembers an EpicStaff page; an app's page is not one, nor anything that is not a path of this app. */
    record(url: string): void {
        if (!isEpicStaffUrl(url) || url === this.recordedUrl()) return;
        this.recordedUrl.set(url);
        this.withStorage((storage) => storage.setItem(RETURN_URL_KEY, url));
    }

    clear(): void {
        this.recordedUrl.set(null);
        this.withStorage((storage) => storage.removeItem(RETURN_URL_KEY));
    }

    private readStored(): string | null {
        const stored = this.withStorage((storage) => storage.getItem(RETURN_URL_KEY)) ?? null;
        return stored !== null && isEpicStaffUrl(stored) ? stored : null;
    }

    /** Storage blocked or full: the way back falls to the default page, nothing fails. */
    private withStorage<Result>(use: (storage: Storage) => Result): Result | undefined {
        try {
            const storage = this.document.defaultView?.sessionStorage;
            return storage ? use(storage) : undefined;
        } catch {
            return undefined;
        }
    }
}

/** An absolute path of this app (not `//host`, which a browser reads as another site) that is not a plugin page. */
function isEpicStaffUrl(url: string): boolean {
    return url.startsWith('/') && !url.startsWith('//') && navigationContextOf(url).kind === 'epicstaff';
}
