import { inject, Injectable } from '@angular/core';
import { StorageService } from '@shared/services';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { CdtExplanation } from '../core/models/classification-decision-table.model';

/** Bumped when the key scheme changes; older entries can never match again. */
const STORAGE_PREFIX = 'cdt-explanation:v3:';
/** Every earlier scheme, `v2` (unscoped) included; swept on first use. */
const LEGACY_PREFIX = 'cdt-explanation:';
/** Entries kept in `localStorage` across every account; the least recently written go first. */
export const CDT_EXPLANATION_CACHE_MAX_ENTRIES = 200;

interface StoredEntry extends CdtExplanation {
    /** `Date.now()` at the write — what eviction orders by. */
    readonly storedAt: number;
}

/**
 * The local half of `CdtExplanationStoreService` — a session `Map` over
 * `localStorage`. Not injected anywhere else; go through the store.
 *
 * Explanations live on the node's `metadata` and so reach the server only once
 * persisted. This layer covers what that leaves open: a persist that never landed,
 * an undo that rolled the canvas back over one, and a rule hidden and later shown
 * again. Written through on every generation, read only when the node has nothing.
 *
 * Keys are step identities, not step content — see `buildExplainStepKeys`. That is
 * what lets an edited step show its old explanation marked outdated instead of
 * showing nothing, and why the value carries a fingerprint.
 *
 * Scoped by organisation, so a shared browser never shows one organisation's text
 * under another's node. Not by user: the explanations are node metadata every
 * member who can open the flow already reads, and `ProfileService` cannot be
 * injected here — it reaches `APP_STORAGE`, which lists this service, so that would
 * be a DI cycle. What a user change needs instead is the clear: memory and
 * `localStorage` both, through `APP_STORAGE` on logout and org switch like every
 * other cache — see `provideVisualProgrammingStorages`.
 */
@Injectable({ providedIn: 'root' })
export class CdtExplanationCacheService implements StorageService {
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly memory = new Map<string, CdtExplanation>();

    constructor() {
        this.removeStorageKeys((key) => key.startsWith(LEGACY_PREFIX) && !key.startsWith(STORAGE_PREFIX));
    }

    public get(key: string): CdtExplanation | null {
        const scopedKey = this.scopedKey(key);
        const local = this.memory.get(scopedKey);
        if (local) return local;

        const stored = this.readStorage(scopedKey);
        if (stored) this.memory.set(scopedKey, stored);
        return stored;
    }

    public set(key: string, value: CdtExplanation): void {
        const scopedKey = this.scopedKey(key);
        this.memory.set(scopedKey, value);
        this.writeStorage(scopedKey, value);
    }

    public clear(): void {
        this.memory.clear();
        this.removeStorageKeys((key) => key.startsWith(STORAGE_PREFIX));
    }

    private scopedKey(key: string): string {
        const orgId = this.activeOrgService.activeOrgId() ?? 'none';
        return `${STORAGE_PREFIX}o${orgId}:${key}`;
    }

    /**
     * Guarded because `localStorage` throws outright in real contexts — private
     * mode, blocked site data, some webviews — and an explanation is a convenience
     * that must never break the dialog.
     */
    private readStorage(storageKey: string): CdtExplanation | null {
        const entry = this.readEntry(storageKey);
        if (!entry) return null;
        const { text, generatedBy, fingerprint } = entry;
        return { text, generatedBy, fingerprint };
    }

    private readEntry(storageKey: string): StoredEntry | null {
        try {
            const raw = localStorage.getItem(storageKey);
            if (!raw) return null;

            const parsed: unknown = JSON.parse(raw);
            if (!parsed || typeof parsed !== 'object') return null;

            const { text, generatedBy, fingerprint, storedAt } = parsed as Partial<Record<keyof StoredEntry, unknown>>;
            if (typeof text !== 'string' || typeof generatedBy !== 'string' || typeof fingerprint !== 'string') {
                return null;
            }

            return { text, generatedBy, fingerprint, storedAt: typeof storedAt === 'number' ? storedAt : 0 };
        } catch {
            return null;
        }
    }

    /** The cap is enforced on every write, not only when the quota runs out. */
    private writeStorage(storageKey: string, value: CdtExplanation): void {
        const entry: StoredEntry = { ...value, storedAt: Date.now() };
        try {
            localStorage.setItem(storageKey, JSON.stringify(entry));
        } catch {
            // Most likely the quota. Evict down to half the cap and retry once; the
            // session Map keeps it either way.
            this.evictOldest(CDT_EXPLANATION_CACHE_MAX_ENTRIES / 2, storageKey);
            try {
                localStorage.setItem(storageKey, JSON.stringify(entry));
            } catch {
                return;
            }
        }
        this.evictOldest(CDT_EXPLANATION_CACHE_MAX_ENTRIES, storageKey);
    }

    /** Drops the least recently written entries until at most `keep` remain; never `protectedKey`. */
    private evictOldest(keep: number, protectedKey: string): void {
        const keys = this.storageKeys((key) => key.startsWith(STORAGE_PREFIX));
        if (keys.length <= keep) return;

        const byAge = keys
            .filter((key) => key !== protectedKey)
            .map((key) => ({ key, storedAt: this.readEntry(key)?.storedAt ?? 0 }))
            .sort((a, b) => a.storedAt - b.storedAt);

        for (const { key } of byAge.slice(0, keys.length - keep)) {
            this.memory.delete(key);
            this.removeStorageKey(key);
        }
    }

    private removeStorageKeys(matches: (key: string) => boolean): void {
        for (const key of this.storageKeys(matches)) this.removeStorageKey(key);
    }

    private removeStorageKey(key: string): void {
        try {
            localStorage.removeItem(key);
        } catch {
            /* nothing left to do */
        }
    }

    private storageKeys(matches: (key: string) => boolean): string[] {
        try {
            const keys: string[] = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && matches(key)) keys.push(key);
            }
            return keys;
        } catch {
            return [];
        }
    }
}
