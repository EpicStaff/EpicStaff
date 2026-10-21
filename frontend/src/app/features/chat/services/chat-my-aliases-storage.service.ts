import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { Subscription } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { ChatBinding, ChatMyAliasResult } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';

/**
 * The names the user goes by on the active org's desks (their aliases), by desk id. Cleared on org switch and logout
 * (`provideChatStorages`); the desks shell loads it with the desks, on every stream `ready` too.
 */
@Injectable({ providedIn: 'root' })
export class ChatMyAliasesStorageService implements StorageService {
    private readonly aliasesSignal = signal<ReadonlyMap<string, string>>(new Map());
    // A load has succeeded for the active org: a desk missing from it has no alias.
    private readonly isLoadedSignal = signal(false);
    // Desks a save answered for: known even before any load has succeeded.
    private readonly savedDesksSignal = signal<ReadonlySet<string>>(new Set());

    readonly aliases = this.aliasesSignal.asReadonly();

    private readonly chatApi = inject(ChatApiService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private request: Subscription | null = null;
    // Saves made while a load is in flight, by desk id: newer than its answer, so they are applied over it.
    private savedDuringLoad = new Map<string, string | null>();

    /**
     * The user's alias on a desk; null when they have none there, and also while that is not known (see `isKnown`).
     * A prefill can use it; a statement about what visitors see must use `visibleNameOn`.
     */
    aliasFor(bindingId: string): string | null {
        return this.aliasesSignal().get(bindingId) ?? null;
    }

    /** Whether the user's alias on a desk is known: once a load has succeeded, or a save answered for that desk. */
    isKnown(bindingId: string): boolean {
        return this.isLoadedSignal() || this.savedDesksSignal().has(bindingId);
    }

    /**
     * The name visitors see on the user's replies on a desk: their alias, else the desk's operator display name. Null
     * while not known (the first load in flight, or every load failed): saying the desk's name then could be false.
     */
    visibleNameOn(binding: ChatBinding): string | null {
        if (!this.isKnown(binding.id)) return null;
        return this.aliasFor(binding.id) ?? binding.operator_display_name;
    }

    /**
     * Fetches the aliases; only the latest request may land. Without an active org (a logout in progress) it asks for
     * nothing. A failed load keeps what is known (replies still go out); until one succeeds, names stay unknown.
     */
    reload(): void {
        if (this.activeOrgService.activeOrgId() === null) return;
        this.request?.unsubscribe();
        const savedDuringThisLoad = new Map<string, string | null>();
        this.savedDuringLoad = savedDuringThisLoad;
        this.request = this.chatApi.getMyAliases().subscribe({
            next: (aliases) => {
                const loaded = new Map(aliases.map(({ binding_id, alias }) => [binding_id, alias]));
                savedDuringThisLoad.forEach((alias, bindingId) => setAlias(loaded, bindingId, alias));
                this.aliasesSignal.set(loaded);
                this.isLoadedSignal.set(true);
                this.request = null;
            },
            error: () => (this.request = null),
        });
    }

    /** A save's answer, shown at once: the alias it stored, or none once cleared. That desk's name is known from now. */
    remember(result: ChatMyAliasResult): void {
        if (this.request) this.savedDuringLoad.set(result.binding_id, result.alias);
        this.aliasesSignal.update((aliases) => setAlias(new Map(aliases), result.binding_id, result.alias));
        this.savedDesksSignal.update((desks) => new Set(desks).add(result.binding_id));
    }

    /** Org switch or logout: the previous org's names must not show, and a load still in flight must not land. */
    clear(): void {
        this.request?.unsubscribe();
        this.request = null;
        this.savedDuringLoad = new Map();
        this.aliasesSignal.set(new Map());
        this.isLoadedSignal.set(false);
        this.savedDesksSignal.set(new Set());
    }
}

function setAlias(aliases: Map<string, string>, bindingId: string, alias: string | null): Map<string, string> {
    if (alias) aliases.set(bindingId, alias);
    else aliases.delete(bindingId);
    return aliases;
}
