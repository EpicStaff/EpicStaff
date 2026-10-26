import { EnvironmentProviders, inject, makeEnvironmentProviders, provideEnvironmentInitializer } from '@angular/core';

import { GUIDED_TOUR_FACTORIES, GuidedTourRegistry, TourDefinitionFactory } from './guided-tour-registry.service';

/**
 * Registers tours with the app (in app.config.ts), in the order auto-start considers them. The definitions are built
 * and checked as the app starts: in dev mode a mistake fails the start with every problem listed; in production it is
 * logged and the tours concerned are left out.
 *
 * Where progress is saved is not bound here: bind TOUR_PROGRESS_STORE at the composition root, next to this call. It
 * has no default, so GuidedTourService cannot be created without it. Until the backend has generic per-tour storage,
 * the only store (the Quick Start feature's ProfileTourProgressStore) can persist the `quick-start` key alone: any
 * other `until-completed` tour would fail to save its completion and auto-start again at every sign-in.
 */
export function provideGuidedTours(...factories: readonly TourDefinitionFactory[]): EnvironmentProviders {
    return makeEnvironmentProviders([
        ...factories.map((factory) => ({ provide: GUIDED_TOUR_FACTORIES, useValue: factory, multi: true })),
        provideEnvironmentInitializer(() => {
            inject(GuidedTourRegistry);
        }),
    ]);
}
