import type { DriveStep } from 'driver.js';

const LAYER_CLASS = 'quickstart-tour-layer';
/** What driver.js appends to <body>: the dimming overlay (created once) and the popover (re-created every step). */
const DRIVER_ELEMENTS_SELECTOR = ':scope > .driver-overlay, :scope > .driver-popover';
const CDK_OVERLAY_PANE_SELECTOR = '.cdk-overlay-pane';
/** The class driver.js puts on the highlighted element. */
const DRIVER_ACTIVE_ELEMENT_SELECTOR = '.driver-active-element';

/**
 * Keeps the driver.js overlay and popover above CDK overlays, and CDK overlays that open mid-step usable.
 *
 * Angular CDK renders every overlay (select dropdowns such as the Quickstart provider list, dialogs, toasts) in the
 * browser top layer through the Popover API. The top layer paints above every z-index, so driver.js's body-level
 * elements would sit under them. This puts them into a `popover="manual"` host of our own, and re-shows that host —
 * the last-shown popover is on top — whenever a step starts or renders, because a CDK overlay may have opened since.
 * An overlay that opens while a step is showing (e.g. a route guard's unsaved-changes dialog) stays above the tour
 * until the next step; _quick-start-tour.scss keeps it clickable, and this keeps Tab inside it.
 *
 * driver.js has no option to mount elsewhere, and its overlay is an <svg>, which cannot be a popover itself, hence
 * the host. Clicks are unaffected: the host ignores pointer events and driver.js sets them per element.
 */
export class TourTopLayer {
    private host: HTMLElement | null = null;
    /** Once disposed the layer stays gone: late hooks of a torn-down tour must not re-create the host. */
    private disposed = false;

    /**
     * driver.js traps Tab (a listener on window) between its popover and the highlighted element, which would pull
     * focus out of a CDK overlay that opened mid-step into the popover under it. There Tab belongs to the overlay's own
     * focus trap, so the event stops at the document before driver.js sees it. Not for the highlighted provider
     * dropdown, which is part of the step.
     */
    private readonly keepTabInOverlay = (event: KeyboardEvent): void => {
        if (event.key !== 'Tab' || !(event.target instanceof Element)) {
            return;
        }
        const pane = event.target.closest(CDK_OVERLAY_PANE_SELECTOR);
        if (
            pane &&
            !pane.matches(DRIVER_ACTIVE_ELEMENT_SELECTOR) &&
            !pane.querySelector(DRIVER_ACTIVE_ELEMENT_SELECTOR)
        ) {
            event.stopPropagation();
        }
    };

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

    /** Idempotent. driver.js removes its own elements on destroy; this removes the host. */
    dispose(): void {
        this.disposed = true;
        this.document.removeEventListener('keydown', this.keepTabInOverlay);
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
        // The DOM ignores a second registration of the same listener, so re-creating the host does not add another.
        this.document.addEventListener('keydown', this.keepTabInOverlay);
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
