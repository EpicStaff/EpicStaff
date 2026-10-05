import type { DriveStep } from 'driver.js';

const LAYER_CLASS = 'quickstart-tour-layer';
/** What driver.js appends to <body>: the dimming overlay (created once) and the popover (re-created every step). */
const DRIVER_ELEMENTS_SELECTOR = ':scope > .driver-overlay, :scope > .driver-popover';

/**
 * Keeps the driver.js overlay and popover above CDK overlays.
 *
 * Angular CDK renders every overlay (the Settings dialog, select dropdowns, toasts) in the browser top layer through
 * the Popover API. The top layer paints above every z-index, so driver.js's body-level elements would sit under the
 * dialog. This puts them into a `popover="manual"` host of our own, and re-shows that host — the last-shown popover is
 * on top — whenever a step starts or renders, because a CDK overlay may have opened since.
 *
 * driver.js has no option to mount elsewhere, and its overlay is an <svg>, which cannot be a popover itself, hence
 * the host. Clicks are unaffected: the host ignores pointer events and driver.js sets them per element.
 */
export class TourTopLayer {
    private host: HTMLElement | null = null;
    /** Once disposed the layer stays gone: late hooks of a torn-down tour must not re-create the host. */
    private disposed = false;

    constructor(private readonly document: Document) {}

    /** Moves driver.js's elements into the host and raises the host above everything else in the top layer. */
    raise(): void {
        if (this.disposed) {
            return;
        }
        const host = this.ensureHost();
        this.document.body.querySelectorAll<Element>(DRIVER_ELEMENTS_SELECTOR).forEach((element) => {
            host.appendChild(element);
        });
        // Without the Popover API (old browsers, jsdom) there is no top layer to compete with.
        if (typeof host.showPopover !== 'function') {
            return;
        }
        // Hiding a popover can move focus out of it; keep it on the popover button driver.js focused.
        const focusedElement = this.document.activeElement;
        if (host.matches(':popover-open')) {
            host.hidePopover();
        }
        host.showPopover();
        if (focusedElement instanceof HTMLElement && host.contains(focusedElement)) {
            focusedElement.focus();
        }
    }

    /** Mounts a tour-owned element (e.g. the confetti canvas) in the host, so it paints above CDK overlays too. */
    append(element: HTMLElement): void {
        if (this.disposed) {
            return;
        }
        this.ensureHost().appendChild(element);
    }

    /** Idempotent. driver.js removes its own elements on destroy; this removes the host and what was appended. */
    dispose(): void {
        this.disposed = true;
        const host = this.host;
        this.host = null;
        if (!host) {
            return;
        }
        if (typeof host.hidePopover === 'function' && host.matches(':popover-open')) {
            host.hidePopover();
        }
        host.remove();
    }

    private ensureHost(): HTMLElement {
        if (this.host?.isConnected) {
            return this.host;
        }
        const host = this.document.createElement('div');
        host.className = LAYER_CLASS;
        host.setAttribute('popover', 'manual');
        this.document.body.appendChild(host);
        this.host = host;
        return host;
    }
}

/**
 * Wraps every step's hooks so the layer is raised when a step starts (the overlay already exists), when its popover
 * renders (driver.js re-creates it per step) and when the highlight finishes (the overlay is created on the first one).
 * The steps' own hooks still run.
 */
export function withTopLayer(steps: DriveStep[], layer: TourTopLayer): DriveStep[] {
    return steps.map((step) => {
        const { onHighlightStarted, onHighlighted } = step;
        const onPopoverRender = step.popover?.onPopoverRender;

        return {
            ...step,
            onHighlightStarted: (...args) => {
                layer.raise();
                onHighlightStarted?.(...args);
            },
            onHighlighted: (...args) => {
                layer.raise();
                onHighlighted?.(...args);
            },
            popover: {
                ...step.popover,
                onPopoverRender: (...args) => {
                    layer.raise();
                    onPopoverRender?.(...args);
                },
            },
        };
    });
}
