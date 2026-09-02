import { Injectable } from '@angular/core';

import { CdtExplanation } from '../core/models/classification-decision-table.model';

/** Bumped when the key scheme changes; older entries can never match again. */
const STORAGE_PREFIX = 'cdt-explanation:v2:';
const LEGACY_PREFIXES = ['cdt-explanation:'];
const MAX_ENTRIES = 200;

/**
 * The local half of `CdtExplanationStoreService` — a session `Map` over
 * `localStorage`. Not injected anywhere else; go through the store.
 *
 * Explanations live on the node's `metadata` and so reach the server only on save.
 * This layer covers what that leaves open: a generation the user never saved, an
 * undo that rolled the canvas back over one, and a rule hidden and later shown
 * again. Written through on every generation, read only when the node has nothing.
 *
 * Keys are step identities, not step content — see `buildExplainStepKeys`. That is
 * what lets an edited step show its old explanation marked outdated instead of
 * showing nothing, and why the value carries a fingerprint.
 */
@Injectable({ providedIn: 'root' })
export class CdtExplanationCacheService {
    private readonly memory = new Map<string, CdtExplanation>();

    constructor() {
        this.dropStalePrefixes();
    }

    public get(key: string): CdtExplanation | null {
        const local = this.memory.get(key);
        if (local) return local;

        const stored = this.readStorage(key);
        if (stored) this.memory.set(key, stored);
        return stored;
    }

    public set(key: string, value: CdtExplanation): void {
        this.memory.set(key, value);
        this.writeStorage(key, value);
    }

    /**
     * Guarded because `localStorage` throws outright in real contexts — private
     * mode, blocked site data, some webviews — and an explanation is a convenience
     * that must never break the dialog.
     */
    private readStorage(key: string): CdtExplanation | null {
        try {
            const raw = localStorage.getItem(STORAGE_PREFIX + key);
            if (!raw) return null;

            const parsed: unknown = JSON.parse(raw);
            if (!parsed || typeof parsed !== 'object') return null;

            const { text, generatedBy, fingerprint } = parsed as {
                text?: unknown;
                generatedBy?: unknown;
                fingerprint?: unknown;
            };
            if (typeof text !== 'string' || typeof generatedBy !== 'string' || typeof fingerprint !== 'string') {
                return null;
            }

            return { text, generatedBy, fingerprint };
        } catch {
            return null;
        }
    }

    private writeStorage(key: string, value: CdtExplanation): void {
        try {
            localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
        } catch {
            // Most likely the quota. Trim and retry once; the session Map keeps it
            // either way.
            this.trimStorage();
            try {
                localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
            } catch {
                /* nothing left to do */
            }
        }
    }

    private trimStorage(): void {
        this.forEachKey(
            (key) => key.startsWith(STORAGE_PREFIX),
            (keys) => {
                for (const key of keys.slice(0, Math.max(1, keys.length - MAX_ENTRIES / 2))) {
                    localStorage.removeItem(key);
                }
            }
        );
    }

    private dropStalePrefixes(): void {
        this.forEachKey(
            (key) => LEGACY_PREFIXES.some((prefix) => key.startsWith(prefix) && !key.startsWith(STORAGE_PREFIX)),
            (keys) => {
                for (const key of keys) localStorage.removeItem(key);
            }
        );
    }

    private forEachKey(matches: (key: string) => boolean, act: (keys: readonly string[]) => void): void {
        try {
            const keys: string[] = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && matches(key)) keys.push(key);
            }
            act(keys);
        } catch {
            /* nothing left to do */
        }
    }
}
