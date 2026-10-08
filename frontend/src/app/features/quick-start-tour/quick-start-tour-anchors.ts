/**
 * The DOM contract between the Quick Start tour and the templates it walks through. Dependency-free on purpose, so any
 * template can import it.
 *
 * 1. `data-tour` anchors: templates bind these values with `[attr.data-tour]`; the tour selects them with
 *    `tourAnchor()`.
 * 2. The result card's status attribute (`QUICK_START_RESULT_STATUS_ATTRIBUTE`), from which the done step picks its
 *    copy. Angular cannot bind an attribute name from a constant, so the template spells it out as
 *    `[attr.data-quickstart-status]` — keep the two in sync.
 */
export const QUICK_START_TOUR_ANCHORS = {
    sidenavSettings: 'sidenav-settings',
    quickstartTab: 'quickstart-tab',
    quickstartProvider: 'quickstart-provider',
    quickstartProviderList: 'quickstart-provider-list',
    quickstartApiKey: 'quickstart-api-key',
    quickstartActivate: 'quickstart-activate',
    /** Present only after Activate succeeded in the current dialog — the tour waits for it to move on. */
    quickstartResult: 'quickstart-result',
} as const;

export type QuickStartTourAnchor = (typeof QUICK_START_TOUR_ANCHORS)[keyof typeof QUICK_START_TOUR_ANCHORS];

export const QUICK_START_RESULT_STATUS_ATTRIBUTE = 'data-quickstart-status';

/**
 * Which result card Activate produced. 'activated': Quickstart was applied to the default models. 'updated': the user
 * already had a Quickstart config, so the provider is saved but the defaults change only after "Update default models".
 */
export type QuickStartResultStatus = 'activated' | 'updated';

/** Selector for an element marked with `data-tour="<anchor>"`. */
export function tourAnchor(anchor: QuickStartTourAnchor): string {
    return `[data-tour="${anchor}"]`;
}
