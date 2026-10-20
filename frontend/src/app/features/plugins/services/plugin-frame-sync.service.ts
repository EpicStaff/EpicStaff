import { DOCUMENT } from '@angular/common';
import { effect, inject, Injectable, OnDestroy, untracked } from '@angular/core';

import {
    PLUGIN_FRAME_ERROR_CODES,
    PLUGIN_FRAME_LIMITS,
    PLUGIN_FRAME_MESSAGE_TYPES,
    PLUGIN_FRAME_PROTOCOL_VERSION,
} from '../constants/plugin-frame-protocol.constants';
import {
    PluginFrameErrorMessage,
    PluginFrameInitMessage,
    PluginFrameOrg,
    PluginNavNavigateMessage,
    PluginTheme,
    PluginThemeChangedMessage,
} from '../models/plugin-frame-protocol.model';
import { canonicalNavPath, PLUGIN_ROOT_NAV_PATH } from '../utils/plugin-nav-path.util';
import { PluginHostThemeService } from './plugin-host-theme.service';

/** What the host page tells the service about the frame it opened. */
export interface PluginFrameAttachOptions {
    /** The validated plugin origin: the only origin whose `es:ready` counts, and the only target of `es:init`. */
    frameOrigin: string;
    /** The page's path when the frame opened. */
    initialPath: string;
    /** The active organization, sent in `es:init`. */
    org: PluginFrameOrg;
    /** The page reported a new path (canonical, within the rate limit); EpicStaff mirrors it in its address. */
    onNavChanged: (path: string, replace: boolean) => void;
}

/** Everything that belongs to one attached frame; dropped as a whole on detach. */
interface FrameAttachment {
    /** Its `contentWindow` is read on every message: the frame's current window, `null` once it is removed. */
    readonly frame: HTMLIFrameElement;
    readonly options: PluginFrameAttachOptions;
    port: MessagePort | null;
    /** The path the page is known to show; `nav.navigate` to it sends nothing. */
    navPath: string;
    /** The theme the page last got, in `es:init` or `theme.changed`. */
    sentTheme: PluginTheme | null;
    /** Kept across handshakes: a page that reloads is the same frame to its rate limit. */
    navChangeTimes: number[];
}

const RATE_WINDOW_MS = 60_000;

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * EpicStaff's side of frame protocol 1 for one framed plugin page (provide it on the host page component).
 *
 * Handshake: accepts `es:ready` posted on `window` only when `event.source` is the frame's window **and**
 * `event.origin` is the plugin origin, then answers `es:init` (theme, path, organization) to that exact origin with
 * a `MessagePort`, or `es:error` when the page speaks another protocol. A later `es:ready` (the page reloaded) closes
 * the old port and repeats `es:init`.
 *
 * On the port: `nav.changed` from the page (canonical paths only, at most 120 a minute, the rest dropped) goes to
 * {@link PluginFrameAttachOptions.onNavChanged}; EpicStaff sends `nav.navigate` ({@link notifyNavigation}) and
 * `theme.changed`. Unknown message types are ignored. Nothing here carries credentials.
 */
@Injectable()
export class PluginFrameSyncService implements OnDestroy {
    private readonly themeEffect = effect(() => {
        const theme = this.themeService.theme();
        untracked(() => this.sendTheme(theme));
    });

    private readonly themeService = inject(PluginHostThemeService);
    private readonly hostWindow = inject(DOCUMENT).defaultView;
    private attachment: FrameAttachment | null = null;
    private readonly windowMessageListener = (event: MessageEvent): void => this.handleWindowMessage(event);

    ngOnDestroy(): void {
        this.detach();
    }

    /** Starts listening for the frame's handshake. Call it before the frame gets its address. */
    attach(frame: HTMLIFrameElement, options: PluginFrameAttachOptions): void {
        this.detach();
        if (!this.hostWindow) return;
        this.attachment = {
            frame,
            options,
            port: null,
            navPath: canonicalNavPath(options.initialPath) ?? PLUGIN_ROOT_NAV_PATH,
            sentTheme: null,
            navChangeTimes: [],
        };
        this.hostWindow.addEventListener('message', this.windowMessageListener);
    }

    /**
     * EpicStaff's address now names `path` below the plugin (back/forward, a link). Tells the page with `nav.navigate`
     * unless it already shows that path; before the handshake, `es:init` carries it instead.
     */
    notifyNavigation(path: string): void {
        const attachment = this.attachment;
        if (!attachment) return;
        const canonical = canonicalNavPath(path) ?? PLUGIN_ROOT_NAV_PATH;
        if (canonical === attachment.navPath) return;
        attachment.navPath = canonical;
        const message: PluginNavNavigateMessage = { type: PLUGIN_FRAME_MESSAGE_TYPES.navNavigate, path: canonical };
        attachment.port?.postMessage(message);
    }

    /** Closes the port and stops listening. Leaves the frame in place. */
    detach(): void {
        const attachment = this.attachment;
        if (!attachment) return;
        this.attachment = null;
        this.hostWindow?.removeEventListener('message', this.windowMessageListener);
        this.closePort(attachment);
    }

    private handleWindowMessage(event: MessageEvent): void {
        const attachment = this.attachment;
        const frameWindow = attachment?.frame.contentWindow;
        if (!attachment || !frameWindow) return;
        if (event.source !== frameWindow || event.origin !== attachment.options.frameOrigin) return;
        const data: unknown = event.data;
        if (!isRecord(data) || data['type'] !== PLUGIN_FRAME_MESSAGE_TYPES.ready) return;

        // A page that posts `es:ready` again has reloaded: whatever it had is gone, so is its port.
        this.closePort(attachment);
        if (data['protocol'] !== PLUGIN_FRAME_PROTOCOL_VERSION) {
            const error: PluginFrameErrorMessage = {
                type: PLUGIN_FRAME_MESSAGE_TYPES.error,
                protocol: PLUGIN_FRAME_PROTOCOL_VERSION,
                code: PLUGIN_FRAME_ERROR_CODES.unsupportedProtocol,
            };
            frameWindow.postMessage(error, attachment.options.frameOrigin);
            return;
        }

        const channel = new MessageChannel();
        attachment.port = channel.port1;
        channel.port1.onmessage = (portEvent: MessageEvent): void => this.handlePortMessage(attachment, portEvent.data);
        const theme = this.themeService.theme();
        attachment.sentTheme = theme;
        const init: PluginFrameInitMessage = {
            type: PLUGIN_FRAME_MESSAGE_TYPES.init,
            protocol: PLUGIN_FRAME_PROTOCOL_VERSION,
            theme,
            nav: { path: attachment.navPath },
            org: { id: attachment.options.org.id, name: attachment.options.org.name },
        };
        frameWindow.postMessage(init, attachment.options.frameOrigin, [channel.port2]);
    }

    private handlePortMessage(attachment: FrameAttachment, data: unknown): void {
        if (this.attachment !== attachment || !isRecord(data)) return;
        if (data['type'] !== PLUGIN_FRAME_MESSAGE_TYPES.navChanged) return;
        if (!this.consumeNavChange(attachment)) return;
        const path = canonicalNavPath(data['path']);
        if (path === null) return;
        attachment.navPath = path;
        attachment.options.onNavChanged(path, data['replace'] === true);
    }

    /** Counts one `nav.changed` in a sliding 60-second window; `false` once the window is full. */
    private consumeNavChange(attachment: FrameAttachment): boolean {
        const now = Date.now();
        attachment.navChangeTimes = attachment.navChangeTimes.filter((time) => now - time < RATE_WINDOW_MS);
        if (attachment.navChangeTimes.length >= PLUGIN_FRAME_LIMITS.maxNavChangesPerMinute) return false;
        attachment.navChangeTimes.push(now);
        return true;
    }

    private sendTheme(theme: PluginTheme): void {
        const attachment = this.attachment;
        if (!attachment?.port || attachment.sentTheme === theme) return;
        attachment.sentTheme = theme;
        const message: PluginThemeChangedMessage = { type: PLUGIN_FRAME_MESSAGE_TYPES.themeChanged, theme };
        attachment.port.postMessage(message);
    }

    private closePort(attachment: FrameAttachment): void {
        if (attachment.port) {
            attachment.port.onmessage = null;
            attachment.port.close();
            attachment.port = null;
        }
        attachment.sentTheme = null;
    }
}
