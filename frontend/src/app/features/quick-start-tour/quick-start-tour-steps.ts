import type { DriverHook, DriveStep, PopoverDOM } from 'driver.js';

import {
    QUICK_START_RESULT_STATUS_ATTRIBUTE,
    QUICK_START_TOUR_ANCHORS,
    QuickStartResultStatus,
    tourAnchor,
} from './quick-start-tour-anchors';

/**
 * Time to wait for a target that appears only after a user action (the Settings dialog, the provider dropdown).
 * driver.js watches the DOM (children and attributes) and highlights the target as soon as it appears; on timeout
 * it shows the step centred.
 */
const TARGET_WAIT_MS = 1500;
/**
 * The confetti canvas is mounted in the tour's top-layer host (see tour-top-layer.ts), next to the driver.js overlay
 * (z-index 10000) and popover (1e9): above the overlay so it is not dimmed, below the popover so it does not cover it.
 */
const CONFETTI_Z_INDEX = 10001;
const CONFETTI_DURATION_MS = 900;
/** Design tokens used for the confetti colours; canvas-confetti needs resolved hex values, not var() references. */
const CONFETTI_COLOR_TOKENS = [
    '--accent-color',
    '--color-ks-status-blue',
    '--color-ks-status-new',
    '--color-ks-status-failed',
    '--color-ks-status-warning',
];
const PROGRESS_CLASS = 'quickstart-tour--has-progress';

export const QUICK_START_TOUR_POPOVER_CLASS = 'quickstart-tour';

/** Done-step copy per result card (see QuickStartResultStatus). */
const RESULT_COPY: Record<QuickStartResultStatus, { title: string; description: string }> = {
    activated: {
        title: 'You’re all set',
        description:
            '<p>Review or change your models any time under Settings → Default LLMs.</p><p>You can replay this tour from your account menu.</p>',
    },
    updated: {
        title: 'One more step',
        description:
            '<p>Your new provider is saved, but your default models have not changed yet.</p><p>Click <strong>Update default models</strong> to apply it, or Finish to keep your current defaults.</p>',
    },
};

export interface QuickStartTourStepsDependencies {
    document: Document;
    openSettingsDialog: () => void;
    /** Closes the dialog as part of the tour (Back) — not treated as the user leaving the tour. */
    closeSettingsDialog: () => void;
    /** Records the tour as completed and ends it. Used by every explicit exit (Skip, Finish). */
    finishTour: () => void;
    /** Mounts a tour-owned element in the tour's top layer, so it paints above CDK overlays; removed with the tour. */
    mountInTourLayer: (element: HTMLElement) => void;
}

const moveNext: DriverHook = (_element, _step, { driver }) => driver.moveNext();
const movePrevious: DriverHook = (_element, _step, { driver }) => driver.movePrevious();

export function createQuickStartTourSteps(dependencies: QuickStartTourStepsDependencies): DriveStep[] {
    const finishTour: DriverHook = () => dependencies.finishTour();
    let stopWatchingForResult: (() => void) | null = null;
    let stopFinishingOnResultClick: (() => void) | null = null;

    const steps: DriveStep[] = [
        {
            popover: {
                popoverClass: `${QUICK_START_TOUR_POPOVER_CLASS} quickstart-tour--welcome`,
                // driver.js labels its dialog by the title element (aria-labelledby); without a title that element
                // still holds the placeholder "Popover Title". The title is visually hidden here, because the design
                // puts the image above the heading, and the visible heading in the description is aria-hidden.
                title: 'Welcome to Quick Start!',
                description: `
                    <img class="quickstart-tour__welcome-image" src="assets/quick-start-guide/quick-start-guide-welcome.webp" alt="" width="276" height="283" draggable="false" />
                    <h3 class="quickstart-tour__welcome-title" aria-hidden="true">&#128640; Welcome to Quick Start!</h3>
                    <p>Connect an AI provider and EpicStaff sets up your default models for you.</p>
                    <p>Follow a few simple steps to set up your workspace and start exploring.</p>
                `,
                nextBtnText: 'Get started',
                // The "previous" slot doubles as Skip here: driver.js has no other secondary button.
                prevBtnText: 'Skip',
                disableButtons: [],
                onPrevClick: finishTour,
            },
        },
        {
            element: tourAnchor(QUICK_START_TOUR_ANCHORS.sidenavSettings),
            // Clicking the Settings icon opens the dialog (sidenav handler) and then runs onNextClick.
            // A click during driver's ~400ms highlight transition is not routed to advanceOnClick; Next still
            // recovers, because open() returns the already open dialog's ref.
            advanceOnClick: true,
            popover: {
                title: 'Open Settings',
                description:
                    'Click the Settings icon. This is where your models, secrets and integrations are configured.',
                side: 'right',
                onNextClick: (element, step, options) => {
                    // Idempotent: when the user clicked the icon the dialog is already open.
                    dependencies.openSettingsDialog();
                    moveNext(element, step, options);
                },
            },
        },
        {
            element: tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartTab),
            waitForElement: TARGET_WAIT_MS,
            popover: {
                title: 'Quickstart',
                description:
                    'Quickstart is the fastest way to get going: one provider and one API key configure your default models.',
                side: 'bottom',
                onPrevClick: (element, step, options) => {
                    dependencies.closeSettingsDialog();
                    movePrevious(element, step, options);
                },
            },
        },
        {
            element: tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartProvider),
            waitForElement: TARGET_WAIT_MS,
            // Clicking the select opens its dropdown; the next step waits for it to render.
            advanceOnClick: true,
            popover: {
                title: 'Pick a provider',
                description: 'Click the dropdown to choose your AI provider.',
                side: 'right',
                showButtons: ['previous', 'close'],
            },
        },
        {
            element: tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartProviderList),
            waitForElement: TARGET_WAIT_MS,
            // Clicking an option selects it (and closes the dropdown); the click lands inside the highlighted list.
            advanceOnClick: true,
            popover: {
                title: 'Select a provider',
                description: 'Pick one from the list to continue.',
                side: 'right',
                // "Previous" would highlight the select while its dropdown stays open on top of it.
                showButtons: ['close'],
            },
        },
        {
            element: tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartApiKey),
            waitForElement: TARGET_WAIT_MS,
            popover: {
                title: 'Add your API key',
                description:
                    'Paste the API key from your provider dashboard. It is stored as a secret and used only to call that provider.',
                side: 'bottom',
                // The provider list only exists while the dropdown is open, so step back past it.
                onPrevClick: (_element, _step, { driver }) =>
                    driver.moveTo(
                        steps.findIndex(
                            (step) => step.element === tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartProvider)
                        )
                    ),
            },
        },
        {
            element: tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartActivate),
            waitForElement: TARGET_WAIT_MS,
            // No Next and no advance-on-click: the click only starts the request. The step moves on when the
            // quickstart section renders its success card, so a failed request leaves the user here.
            onHighlighted: (_element, _step, { driver }) => {
                stopWatchingForResult?.();
                stopWatchingForResult = whenElementAppears(
                    dependencies.document,
                    tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartResult),
                    () => {
                        stopWatchingForResult = null;
                        if (driver.isActive()) {
                            driver.moveNext();
                        }
                    }
                );
            },
            onDeselected: () => {
                stopWatchingForResult?.();
                stopWatchingForResult = null;
            },
            popover: {
                title: 'Activate',
                description:
                    'Click Activate. EpicStaff creates the configurations for your provider and applies them as your default models.',
                side: 'top',
                showButtons: ['previous', 'close'],
            },
        },
        {
            element: tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartResult),
            onHighlighted: (element) => {
                if (resultStatus(element) === 'activated') {
                    void fireConfetti(dependencies.document, dependencies.mountInTourLayer);
                }
                stopFinishingOnResultClick?.();
                stopFinishingOnResultClick = element ? finishOnAnyClick(element, dependencies.finishTour) : null;
            },
            onDeselected: () => {
                stopFinishingOnResultClick?.();
                stopFinishingOnResultClick = null;
            },
            popover: {
                // Placeholder; replaced in onPopoverRender with the copy for the card the user actually got.
                title: RESULT_COPY.activated.title,
                description: RESULT_COPY.activated.description,
                side: 'left',
                doneBtnText: 'Finish',
                showButtons: ['next', 'close'],
                onNextClick: finishTour,
                onPopoverRender: (popover) => {
                    const card = dependencies.document.querySelector(
                        tourAnchor(QUICK_START_TOUR_ANCHORS.quickstartResult)
                    );
                    const copy = resultStatus(card) === 'updated' ? RESULT_COPY.updated : RESULT_COPY.activated;
                    popover.title.textContent = copy.title;
                    popover.description.innerHTML = copy.description;
                },
            },
        },
    ];

    return withProgressBar(steps);
}

/** The result card's status attribute, rendered by the quickstart section; null for anything unexpected. */
function resultStatus(card: Element | null | undefined): QuickStartResultStatus | null {
    const status = card?.getAttribute(QUICK_START_RESULT_STATUS_ATTRIBUTE);
    return status === 'activated' || status === 'updated' ? status : null;
}

/**
 * Ends the tour on any click inside `element`, without stopping the click. Capture phase, so the tour is torn down
 * (overlay, top-layer host, driver's page-wide pointer-events lock) before the clicked control's own handler runs —
 * e.g. "Update default models" opens a confirm dialog that must be usable. driver.js's own `advanceOnClick` is not
 * used: it listens in the bubble phase, after that handler, and ignores clicks during its highlight animation.
 */
function finishOnAnyClick(element: Element, finishTour: () => void): () => void {
    const onClick = (): void => finishTour();
    element.addEventListener('click', onClick, { capture: true });
    return () => element.removeEventListener('click', onClick, { capture: true });
}

/**
 * Calls `onFound` once `selector` matches (now or after a DOM change). Returns a function that stops watching.
 * Event-driven (MutationObserver), not polling, and with no timeout: the Activate step should wait as long as the
 * user needs to fix a rejected key.
 */
function whenElementAppears(document: Document, selector: string, onFound: () => void): () => void {
    if (document.querySelector(selector)) {
        onFound();
        return () => undefined;
    }
    const MutationObserverConstructor = document.defaultView?.MutationObserver;
    if (!MutationObserverConstructor) {
        return () => undefined;
    }
    const observer = new MutationObserverConstructor(() => {
        if (document.querySelector(selector)) {
            observer.disconnect();
            onFound();
        }
    });
    observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['data-tour'],
    });
    return () => observer.disconnect();
}

/** Adds the top progress bar to every step except the first (welcome) and the last (done). */
function withProgressBar(steps: DriveStep[]): DriveStep[] {
    const progressStepCount = steps.length - 2;

    return steps.map((step, index) => {
        const isProgressStep = index > 0 && index < steps.length - 1;
        const popoverClass = [
            step.popover?.popoverClass ?? QUICK_START_TOUR_POPOVER_CLASS,
            isProgressStep ? PROGRESS_CLASS : null,
        ]
            .filter(Boolean)
            .join(' ');
        const progress = `${(index / progressStepCount) * 100}%`;

        return {
            ...step,
            popover: {
                ...step.popover,
                popoverClass,
                ...(isProgressStep
                    ? {
                          onPopoverRender: (popover: PopoverDOM) =>
                              popover.wrapper.style.setProperty('--tour-progress', progress),
                      }
                    : {}),
            },
        };
    });
}

/**
 * canvas-confetti's default canvas goes to <body>, which is under the top layer (and so under the dimmed overlay).
 * We give it our own canvas mounted in the tour layer instead; the canvas goes away with the layer.
 */
async function fireConfetti(document: Document, mountInTourLayer: (element: HTMLElement) => void): Promise<void> {
    if (document.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
        return;
    }
    const { default: confetti } = await import('canvas-confetti');
    const canvas = document.createElement('canvas');
    Object.assign(canvas.style, {
        position: 'fixed',
        inset: '0',
        width: '100%',
        height: '100%',
        zIndex: String(CONFETTI_Z_INDEX),
        pointerEvents: 'none',
    });
    mountInTourLayer(canvas);
    const shootConfetti = confetti.create(canvas, { resize: true, disableForReducedMotion: true });
    const colors = resolveConfettiColors(document);
    const endTime = performance.now() + CONFETTI_DURATION_MS;
    const shared = {
        particleCount: 4,
        spread: 55,
        ...(colors.length ? { colors } : {}),
    };

    const shoot = (): void => {
        void shootConfetti({ ...shared, angle: 60, origin: { x: 0, y: 0.8 } });
        void shootConfetti({ ...shared, angle: 120, origin: { x: 1, y: 0.8 } });
        if (performance.now() < endTime) {
            requestAnimationFrame(shoot);
        }
    };
    shoot();
}

function resolveConfettiColors(document: Document): string[] {
    const view = document.defaultView;
    if (!view) {
        return [];
    }
    const computedStyle = view.getComputedStyle(document.documentElement);
    return CONFETTI_COLOR_TOKENS.map((token) => computedStyle.getPropertyValue(token).trim()).filter(Boolean);
}
