import { DOCUMENT } from '@angular/common';
import { computed, effect, inject, Injectable, signal, untracked } from '@angular/core';

import { ProfileService } from '../../../services/auth/profile.service';
import { AvailablePluginsStorageService } from './available-plugins-storage.service';

/** `localStorage`, one entry per user and organization: `<prefix>.<user id>.<organization id>`. */
const SEEN_APPS_KEY_PREFIX = 'epicstaff.seenApps';

const NO_APPS: ReadonlySet<string> = new Set();

/**
 * Which of the apps the signed-in user may open in the active organization are new to them: granted since they last
 * opened an apps list. The sidebar marks the Apps row with a dot and the new apps with a tag.
 *
 * The apps already there the first time a user's list lands in an organization are taken as seen, silently: nothing
 * is new before EpicStaff knew what was there. Kept on this device only (`localStorage`); a blocked storage shows
 * nothing as new.
 */
@Injectable({ providedIn: 'root' })
export class SeenAppsService {
    /** Every write; `seen` reads the storage again after one. */
    private readonly writes = signal(0);
    /** `null` until a list landed, for the user and the organization it belongs to. */
    private readonly storageKey = computed(() => {
        const userId = this.profileService.currentUserSignal()?.id;
        const orgId = this.availablePlugins.loadedOrgId();
        return userId !== undefined && orgId !== null ? `${SEEN_APPS_KEY_PREFIX}.${userId}.${orgId}` : null;
    });
    /** `null`: nothing recorded for this user and organization yet (or no storage). */
    private readonly seen = computed<ReadonlySet<string> | null>(() => {
        this.writes();
        const key = this.storageKey();
        return key === null ? null : this.read(key);
    });
    /** Identifiers of the listed apps the user has not seen. */
    readonly newIdentifiers = computed<ReadonlySet<string>>(() => {
        const seen = this.seen();
        if (seen === null) return NO_APPS;
        const added = this.availablePlugins
            .plugins()
            .map((plugin) => plugin.identifier)
            .filter((identifier) => !seen.has(identifier));
        return added.length === 0 ? NO_APPS : new Set(added);
    });

    private readonly seedFirstList = effect(() => {
        const key = this.storageKey();
        if (key === null) return;
        untracked(() => {
            if (this.read(key) === null) this.writeCurrentList(key);
        });
    });

    private readonly availablePlugins = inject(AvailablePluginsStorageService);
    private readonly profileService = inject(ProfileService);
    private readonly document = inject(DOCUMENT);

    /** The user opened an apps list: what it shows now is seen. */
    markSeen(): void {
        const key = this.storageKey();
        if (key !== null) this.writeCurrentList(key);
    }

    private writeCurrentList(key: string): void {
        const identifiers = this.availablePlugins.plugins().map((plugin) => plugin.identifier);
        this.withStorage((storage) => storage.setItem(key, JSON.stringify(identifiers)));
        this.writes.update((count) => count + 1);
    }

    private read(key: string): ReadonlySet<string> | null {
        const stored = this.withStorage((storage) => storage.getItem(key)) ?? null;
        if (stored === null) return null;
        try {
            const parsed: unknown = JSON.parse(stored);
            return Array.isArray(parsed)
                ? new Set(parsed.filter((identifier): identifier is string => typeof identifier === 'string'))
                : null;
        } catch {
            return null;
        }
    }

    private withStorage<Result>(use: (storage: Storage) => Result): Result | undefined {
        try {
            const storage = this.document.defaultView?.localStorage;
            return storage ? use(storage) : undefined;
        } catch {
            return undefined;
        }
    }
}
