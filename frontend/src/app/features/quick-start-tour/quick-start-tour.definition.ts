import { inject } from '@angular/core';

import { SETTINGS_QUICKSTART_URL, SETTINGS_URL } from '../../core/guards/settings.guard';
import type { TourContent, TourDefinition } from '../../core/guided-tour';
import { PermissionsService } from '../../services/auth/permissions.service';
import {
    QUICK_START_RESULT_STATUS_ATTRIBUTE,
    QUICK_START_TOUR_ANCHORS,
    QuickStartResultStatus,
} from './quick-start-tour-anchors';

export const QUICK_START_TOUR_KEY = 'quick-start';

/**
 * Time to wait for a target that appears only after a user action (the Settings page, the provider dropdown). The
 * step shows as soon as it appears; past this, it shows in the centre with nothing highlighted.
 */
const TARGET_WAIT_MS = 1500;

/** Done-step copy per result card (see QuickStartResultStatus). */
const RESULT_CONTENT: Record<QuickStartResultStatus, TourContent> = {
    activated: {
        title: 'You’re all set',
        body: [
            'Review or change your models any time under Settings → Default LLMs.',
            'You can replay this tour from your account menu.',
        ],
    },
    updated: {
        title: 'One more step',
        body: [
            'Your new provider is saved, but your default models have not changed yet.',
            [
                { text: 'Click ' },
                { text: 'Update default models', strong: true },
                { text: ' to apply it, or Finish to keep your current defaults.' },
            ],
        ],
    },
};

/**
 * The Quick Start tour: from the Settings icon to an activated provider. Registered with provideGuidedTours(), which
 * runs this in an injection context.
 */
export function createQuickStartTour(): TourDefinition {
    const permissionsService = inject(PermissionsService);

    return {
        key: QUICK_START_TOUR_KEY,
        label: 'Quick Start Tour',
        icon: 'help',
        autoStart: 'until-completed',
        // The tour walks Settings → Quickstart → Activate, so it needs every permission those gate on.
        isAvailable: () => permissionsService.canOpenConfigureModelsDialog() && permissionsService.canApplyQuickstart(),
        steps: [
            {
                id: 'welcome',
                content: {
                    title: 'Welcome to Quick Start!',
                    media: {
                        src: 'assets/quick-start-guide/quick-start-guide-welcome.webp',
                        width: 276,
                        height: 283,
                    },
                    body: [
                        'Connect an AI provider and EpicStaff sets up your default models for you.',
                        'Follow a few simple steps to set up your workspace and start exploring.',
                    ],
                },
                buttons: { next: 'Get started', skip: 'Skip' },
            },
            {
                id: 'open-settings',
                target: { anchor: QUICK_START_TOUR_ANCHORS.sidenavSettings, side: 'right' },
                content: {
                    title: 'Open Settings',
                    body: [
                        'Click the Settings icon. This is where your models, secrets and integrations are configured.',
                    ],
                },
                // A phone keeps the app navigation closed, so the icon cannot be pointed at; Next still opens Settings.
                fallbackContent: {
                    title: 'Open Settings',
                    body: [
                        'Press Next to open Settings. This is where your models, secrets and integrations are configured.',
                    ],
                },
                // The icon's link goes to the Settings index, which redirects to the Quickstart tab. Moving on waits
                // until the tab shows: leaving the current page may first ask about unsaved changes, and the user may
                // choose to stay.
                advance: {
                    kind: 'navigation',
                    url: SETTINGS_QUICKSTART_URL,
                    followNavigationsInto: SETTINGS_URL,
                    onTargetClick: true,
                },
                showProgress: true,
            },
            {
                id: 'quickstart-tab',
                target: { anchor: QUICK_START_TOUR_ANCHORS.quickstartTab, side: 'bottom', waitMs: TARGET_WAIT_MS },
                content: {
                    title: 'Quickstart',
                    body: [
                        'Quickstart is the fastest way to get going: one provider and one API key configure your default models.',
                    ],
                },
                // From here on every step points inside the Quickstart tab.
                routeScope: SETTINGS_QUICKSTART_URL,
                showProgress: true,
            },
            {
                id: 'pick-provider',
                target: {
                    anchor: QUICK_START_TOUR_ANCHORS.quickstartProvider,
                    side: 'right',
                    waitMs: TARGET_WAIT_MS,
                },
                content: { title: 'Pick a provider', body: ['Click the dropdown to choose your AI provider.'] },
                // The click opens the dropdown; the next step waits for its list to render.
                advance: { kind: 'target-click', timing: 'after-target' },
                buttons: { next: false },
                routeScope: SETTINGS_QUICKSTART_URL,
                showProgress: true,
            },
            {
                id: 'select-provider',
                target: {
                    anchor: QUICK_START_TOUR_ANCHORS.quickstartProviderList,
                    side: 'right',
                    waitMs: TARGET_WAIT_MS,
                },
                content: { title: 'Select a provider', body: ['Pick one from the list to continue.'] },
                // Clicking an option selects it and closes the dropdown.
                advance: { kind: 'target-click', timing: 'after-target' },
                // Back would point at the select while its dropdown stays open on top of it.
                buttons: { next: false, back: false },
                routeScope: SETTINGS_QUICKSTART_URL,
                showProgress: true,
            },
            {
                id: 'api-key',
                target: { anchor: QUICK_START_TOUR_ANCHORS.quickstartApiKey, side: 'bottom', waitMs: TARGET_WAIT_MS },
                content: {
                    title: 'Add your API key',
                    body: [
                        'Paste the API key from your provider dashboard. It is stored as a secret and used only to call that provider.',
                    ],
                },
                // The provider list exists only while the dropdown is open, so Back skips it.
                back: { toStep: 'pick-provider' },
                routeScope: SETTINGS_QUICKSTART_URL,
                showProgress: true,
            },
            {
                id: 'activate',
                target: { anchor: QUICK_START_TOUR_ANCHORS.quickstartActivate, side: 'top', waitMs: TARGET_WAIT_MS },
                content: {
                    title: 'Activate',
                    body: [
                        'Click Activate. EpicStaff creates the configurations for your provider and applies them as your default models.',
                    ],
                },
                // The click only starts the request: the step moves on when the success card renders, so a failed
                // request (e.g. a rejected key) leaves the user here for as long as fixing it takes.
                advance: { kind: 'anchor-appears', anchor: QUICK_START_TOUR_ANCHORS.quickstartResult },
                buttons: { next: false },
                routeScope: SETTINGS_QUICKSTART_URL,
                showProgress: true,
            },
            {
                id: 'done',
                target: { anchor: QUICK_START_TOUR_ANCHORS.quickstartResult, side: 'left' },
                content: (context) =>
                    RESULT_CONTENT[resultStatus(context.targetAttribute(QUICK_START_RESULT_STATUS_ATTRIBUTE))],
                // Any click in the card finishes the tour before the clicked control handles it: "Update default
                // models" opens a confirm dialog, which must not open under the tour.
                advance: { kind: 'target-click', timing: 'before-target' },
                buttons: { next: 'Finish', back: false },
                routeScope: SETTINGS_QUICKSTART_URL,
            },
        ],
    };
}

/** The result card's status, as the quickstart section renders it; `activated` for a missing or unexpected value. */
function resultStatus(status: string | null): QuickStartResultStatus {
    return status === 'updated' ? 'updated' : 'activated';
}
