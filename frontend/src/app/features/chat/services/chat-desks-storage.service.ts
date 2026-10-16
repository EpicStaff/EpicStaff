import { HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';
import { Subscription } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { ToastService } from '../../../services/notifications';
import { ChatBinding } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';

/**
 * The active org's desks, shared by the desk rail and the desk pages. Cleared on org switch and logout
 * (`provideChatStorages`); the desks shell reloads it.
 */
@Injectable({ providedIn: 'root' })
export class ChatDesksStorageService implements StorageService {
    private readonly desksSignal = signal<ChatBinding[]>([]);
    private readonly landedRequestSignal = signal(0);
    private readonly isLoadingSignal = signal(false);
    private readonly loadFailedSignal = signal(false);

    readonly desks = this.desksSignal.asReadonly();
    /**
     * The request whose list `desks` holds, 0 until one lands for the active org. A caller that must know the list is
     * at least as fresh as a request of its own compares this with the number `reload()` returned.
     */
    readonly landedRequest = this.landedRequestSignal.asReadonly();
    readonly isLoaded = computed(() => this.landedRequestSignal() > 0);
    readonly isLoading = this.isLoadingSignal.asReadonly();
    /** No list could be loaded: it must not look like an org without desks and invite duplicate creates. */
    readonly loadFailed = this.loadFailedSignal.asReadonly();

    private readonly chatApi = inject(ChatApiService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly toastService = inject(ToastService);
    // Never reset, so a request number taken before a clear cannot match a list loaded after it.
    private requestCount = 0;
    private request: Subscription | null = null;

    /**
     * Fetches the desks; only the latest request may land. Returns its number (see `landedRequest`), or null when it
     * sent none: without an active org (a logout in progress) there are no desks to ask for, and a cleared storage
     * must stay cleared rather than fill up again under a token that is about to go.
     */
    reload(): number | null {
        if (this.activeOrgService.activeOrgId() === null) return null;
        const request = ++this.requestCount;
        this.request?.unsubscribe();
        this.isLoadingSignal.set(true);
        this.loadFailedSignal.set(false);
        this.request = this.chatApi.getBindings().subscribe({
            next: (desks) => {
                this.desksSignal.set(desks);
                this.landedRequestSignal.set(request);
                this.isLoadingSignal.set(false);
            },
            error: (error: HttpErrorResponse) => {
                this.isLoadingSignal.set(false);
                // A failed reload keeps the desks already shown and only says so.
                if (this.isLoaded()) this.toastService.error(extractHttpErrorMessage(error));
                else this.loadFailedSignal.set(true);
            },
        });
        return request;
    }

    /** Org switch or logout: the previous org's desks must not show, and a request still in flight must not land. */
    clear(): void {
        this.request?.unsubscribe();
        this.request = null;
        this.desksSignal.set([]);
        this.landedRequestSignal.set(0);
        this.isLoadingSignal.set(false);
        this.loadFailedSignal.set(false);
    }
}
