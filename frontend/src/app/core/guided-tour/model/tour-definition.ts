import { TourContent, TourFloatingPosition, TourSide } from './tour-content';

/**
 * When a tour starts. `manual`: only when the user asks for it (e.g. from the account menu). `until-completed`: also
 * by itself, until the user has finished or skipped it; at most once per sign-in, and not after the user started it
 * themselves in that sign-in.
 */
export type TourAutoStart = 'manual' | 'until-completed';

/**
 * A guided tour: the steps it walks through and when it may run. Read by the engine only; how a step is drawn is the
 * renderer's business, so a definition holds data and plain functions, never DOM or overlay code.
 */
export interface TourDefinition {
    /**
     * Stable id, stored with the user's progress. Lowercase letters and digits in words joined by single hyphens, at
     * most 64 characters (e.g. `quick-start`): the rule the profile's tour progress API enforces too. Renaming it
     * makes the tour new to every user.
     */
    readonly key: string;
    /** Names the tour where the user can replay it. */
    readonly label: string;
    /** An `app-svg-icon` sprite id shown next to the label. */
    readonly icon: string;
    readonly autoStart: TourAutoStart;
    /**
     * Whether the signed-in user can take the tour now (e.g. has the permissions its steps rely on). Read in reactive
     * contexts: when a signal it reads changes, an unavailable tour may auto-start. Only starting checks it; a running
     * tour goes on when it turns false, since an org switch clears the permissions for a moment. Should it throw, the
     * error surfaces in dev mode; in production it is logged and the tour counts as unavailable.
     */
    readonly isAvailable: () => boolean;
    /** Escape ends the tour like the close button, on the steps that show the close button. Off by default. */
    readonly closeOnEscape?: boolean;
    /** Shown in this order; at least one. */
    readonly steps: readonly TourStep[];
}

export interface TourStep {
    /** Unique within the tour; `back.toStep` refers to it. */
    readonly id: string;
    /** What the popover says. A function is called every time the step shows, with what it found of the target. */
    readonly content: TourContent | ((context: TourContentContext) => TourContent);
    /** The element the step points at. Without one the popover floats (see `floating`). */
    readonly target?: TourTarget;
    /** Where the popover goes while there is no target, or it is missing or not visible. Default `center`. */
    readonly floating?: TourFloatingPosition;
    /**
     * Shown instead of `content` when the target is missing or not visible as the step shows, e.g. an icon in the app
     * navigation, which a phone keeps closed. Write it so the step still works without the target.
     */
    readonly fallbackContent?: TourContent;
    /** What moves the step on. Default: the Next button only, so hiding Next then needs another advance. */
    readonly advance?: TourAdvance;
    /** Where Back goes. Default: the previous step. */
    readonly back?: TourBack;
    readonly buttons?: TourButtons;
    /**
     * While this step is current, a navigation that ends anywhere but this URL ends the tour as skipped. Only the path
     * counts: query parameters and the fragment may change.
     */
    readonly routeScope?: string;
    /** Counts the step in the progress bar ("Step 2 of 6"); the steps without it are neither counted nor show it. */
    readonly showProgress?: boolean;
}

/** What a content function may read of the page: only what the step's target says about itself, never the DOM. */
export interface TourContentContext {
    /**
     * The value of the attribute `name` on the step's target as found when the step shows; null when the target has
     * no such attribute or did not turn up.
     */
    targetAttribute(name: string): string | null;
}

export interface TourTarget {
    /** The `data-tour` value of the element (see tour-anchor.ts). Follows the same rule as a tour key. */
    readonly anchor: string;
    /** The side of the target the popover prefers. */
    readonly side: TourSide;
    /**
     * How long the step waits for its anchor to appear (a page loading, a dropdown opening) before it shows without
     * it. Default 0: looked up once, when the step starts.
     */
    readonly waitMs?: number;
}

/**
 * When the tour handles a click on its target. `after-target`: once the target and everything inside it handled the
 * click (e.g. a router link has started its navigation). `before-target`: before any of them (e.g. the tour must be
 * gone before a button inside the target opens a dialog). Neither stops the click.
 */
export type TourClickTiming = 'after-target' | 'before-target';

/**
 * What moves a step on, besides the Next button where the step shows it. On the last step, moving on finishes the
 * tour.
 *
 * - `next`: the Next button only.
 * - `target-click`: a click on or inside an element marked with the target's anchor, so a re-render that replaces the
 *   element does not lose it. Needs a `target`.
 * - `anchor-appears`: the anchor appearing on the page (e.g. a result card), however long that takes.
 * - `navigation`: see TourNavigationAdvance.
 */
export type TourAdvance =
    | { readonly kind: 'next' }
    | { readonly kind: 'target-click'; readonly timing: TourClickTiming }
    | { readonly kind: 'anchor-appears'; readonly anchor: string }
    | TourNavigationAdvance;

/**
 * Takes the user to `url`, and moves on once the router has settled there. Next starts the navigation; with
 * `onTargetClick` a click on the target does too, after the target's own handlers. When the navigation settles
 * elsewhere (e.g. the user chose to stay in an unsaved-changes dialog) the step stays, and the user can try again;
 * leaving the step drops a navigation still on its way.
 */
export interface TourNavigationAdvance {
    readonly kind: 'navigation';
    readonly url: string;
    /**
     * A navigation already heading anywhere under this URL (e.g. started by the target's own router link, or by an
     * earlier Next) is followed rather than superseded, so the page being left is not asked about unsaved changes
     * twice. Any other navigation in flight is superseded. Must contain `url`, which is the default.
     */
    readonly followNavigationsInto?: string;
    /** A click on the target starts the navigation too (see `target-click`). Needs a `target`. */
    readonly onTargetClick?: boolean;
}

export interface TourBack {
    /** The id of the step Back goes to, e.g. past a step whose dropdown has closed in the meantime. */
    readonly toStep: string;
}

/** A label shows a button, `false` hides it; leaving one out keeps its default. */
export interface TourButtons {
    /** Default `Next`, and `Finish` on the last step, where it finishes the tour. */
    readonly next?: string | false;
    /** Default `Back`. Never shown on the first step. */
    readonly back?: string | false;
    /** Ends the tour as skipped. Hidden by default. */
    readonly skip?: string | false;
    /** The close button, which ends the tour as skipped. Shown by default. */
    readonly close?: boolean;
}
