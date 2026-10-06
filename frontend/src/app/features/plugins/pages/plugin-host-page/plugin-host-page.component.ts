import { DOCUMENT } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, effect, ElementRef, inject, input, signal, untracked, viewChild } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { FetchErrorStateComponent, LoadingSpinnerComponent } from '@shared/components';
import { catchError, map, Observable, of, switchMap, tap } from 'rxjs';

import { PluginBridgeHost, PluginBridgeStopReason } from '../../bridge/plugin-bridge-host.service';
import { PluginUiSession } from '../../models/plugin.model';
import { PluginsApiService } from '../../services/plugins-api.service';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { toPluginErrorView } from '../../utils/plugin-error.util';
import { toPluginFrameUrl } from '../../utils/plugin-frame-url.util';

interface ReadyView {
    kind: 'ready';
    session: PluginUiSession;
    frameUrl: SafeResourceUrl;
}

/** Every state without a page: suspended / not ready / not found, errors, and a stopped page. */
interface MessageView {
    kind: 'message';
    title: string;
    message: string;
    retryLabel: string;
}

type PluginHostView = { kind: 'loading' } | ReadyView | MessageView;

const STOPPED_MESSAGES: Record<PluginBridgeStopReason, string> = {
    navigated: 'The page tried to open another address, so EpicStaff closed it. Anything it was doing has stopped.',
    org_changed: 'You switched organization, so this plugin page was closed.',
};

/** 409 codes of `ui-session` that mean "the page can't be opened right now". */
const UNAVAILABLE_TITLES: ReadonlyMap<string, string> = new Map([
    ['plugin_suspended', 'This plugin is suspended'],
    ['plugin_not_ready', 'This plugin is not ready yet'],
    ['plugin_has_no_ui', 'This plugin has no page'],
]);

/**
 * `/plugins/:id`: opens a plugin's own page in a sandboxed iframe and serves it the bridge.
 *
 * The iframe gets no token and no same-origin access: `sandbox="allow-scripts"` only, its URL
 * must be a `/api/plugin-ui/` path, and it reaches EpicStaff solely through the
 * {@link PluginBridgeHost} provided here (one per page, destroyed with it).
 */
@Component({
    selector: 'app-plugin-host-page',
    imports: [FetchErrorStateComponent, LoadingSpinnerComponent],
    templateUrl: './plugin-host-page.component.html',
    styleUrl: './plugin-host-page.component.scss',
    providers: [PluginBridgeHost],
})
export class PluginHostPageComponent {
    /** Route param (`withComponentInputBinding`). */
    readonly id = input.required<string>();

    private readonly frame = viewChild<ElementRef<HTMLIFrameElement>>('pluginFrame');

    private readonly attempt = signal(0);
    protected readonly view = signal<PluginHostView>({ kind: 'loading' });
    protected readonly readyView = computed(() => {
        const view = this.view();
        return view.kind === 'ready' ? view : null;
    });
    protected readonly messageView = computed(() => {
        const view = this.view();
        return view.kind === 'message' ? view : null;
    });

    // Attach in the same pass that rendered the iframe with its `src`, before the page can post `ready`.
    private readonly attachEffect = effect(() => {
        const frame = this.frame();
        const ready = this.readyView();
        if (frame && ready) untracked(() => this.bridgeHost.attach(frame.nativeElement, ready.session));
    });

    private readonly stoppedEffect = effect(() => {
        const reason = this.bridgeHost.stopped();
        if (reason) {
            untracked(() =>
                this.view.set({
                    kind: 'message',
                    title: 'Plugin page stopped',
                    message: STOPPED_MESSAGES[reason],
                    retryLabel: 'Reload page',
                })
            );
        }
    });

    private readonly bridgeHost = inject(PluginBridgeHost);
    private readonly pluginsApiService = inject(PluginsApiService);
    private readonly pluginsStore = inject(PluginsStoreService);
    private readonly sanitizer = inject(DomSanitizer);
    private readonly document = inject(DOCUMENT);

    constructor() {
        const request = computed(() => ({ id: this.id(), attempt: this.attempt() }));
        toObservable(request)
            .pipe(
                tap(() => {
                    this.bridgeHost.detach();
                    this.view.set({ kind: 'loading' });
                }),
                switchMap(({ id }) => this.openPage(id)),
                takeUntilDestroyed()
            )
            .subscribe((view) => this.view.set(view));
    }

    protected reload(): void {
        this.attempt.update((attempt) => attempt + 1);
    }

    protected onFrameLoad(): void {
        this.bridgeHost.onFrameLoad();
    }

    private openPage(rawId: string): Observable<PluginHostView> {
        const id = Number(rawId);
        if (!Number.isSafeInteger(id) || id <= 0) {
            return of(messageView('Plugin not found', 'There is no plugin at this address.', 'Try again'));
        }
        return this.pluginsApiService.createUiSession(id).pipe(
            map((session) => this.toReadyView(session)),
            catchError((error: unknown) => of(this.toFailureView(error)))
        );
    }

    private toReadyView(session: PluginUiSession): PluginHostView {
        const url = toPluginFrameUrl(session.url, this.document.location.origin);
        if (url === null) {
            return messageView(
                "Couldn't open the plugin",
                'EpicStaff answered with an unexpected page address, so the page was not loaded.',
                'Retry'
            );
        }
        // The only trusted resource URL: a validated same-origin `/api/plugin-ui/` path.
        return { kind: 'ready', session, frameUrl: this.sanitizer.bypassSecurityTrustResourceUrl(url) };
    }

    private toFailureView(error: unknown): PluginHostView {
        if (!(error instanceof HttpErrorResponse)) {
            return messageView("Couldn't open the plugin", 'Something went wrong. Try again.', 'Retry');
        }
        const errorView = toPluginErrorView(error, 'Check your connection and try again.');
        if (error.status === 404 || error.status === 409) {
            // The navigation button may be stale (suspended, deleted, or no longer ready).
            this.pluginsStore.refreshNav();
        }
        if (error.status === 404) {
            return messageView(
                'Plugin not found',
                'It may have been deleted, or it belongs to another organization.',
                'Try again'
            );
        }
        const unavailableTitle = error.status === 409 ? UNAVAILABLE_TITLES.get(errorView.code ?? '') : undefined;
        if (unavailableTitle) {
            return messageView(unavailableTitle, errorView.message, 'Try again');
        }
        if (error.status === 403) {
            return messageView("You can't open this plugin", errorView.message, 'Try again');
        }
        return messageView("Couldn't open the plugin", errorView.message, 'Retry');
    }
}

function messageView(title: string, message: string, retryLabel: string): MessageView {
    return { kind: 'message', title, message, retryLabel };
}
