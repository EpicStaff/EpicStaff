import { inject, Injectable, InjectionToken, isDevMode } from '@angular/core';

import { TourDefinition } from '../model/tour-definition';
import { validateTourDefinitions } from './validate-tour-definitions';

/** Builds a tour definition. Runs in an injection context, so it can inject what `isAvailable` reads. */
export type TourDefinitionFactory = () => TourDefinition;

/** The registered tours' factories, in registration order. Filled by provideGuidedTours(); read by GuidedTourRegistry. */
export const GUIDED_TOUR_FACTORIES = new InjectionToken<readonly TourDefinitionFactory[]>('GUIDED_TOUR_FACTORIES');

/**
 * The registered tours, built and checked once (see registeredTours), so a definition mistake shows at startup rather
 * than in the middle of a tour.
 */
@Injectable({
    providedIn: 'root',
})
export class GuidedTourRegistry {
    /** The valid ones, in registration order, which is also the order auto-start considers them in. */
    readonly tours: readonly TourDefinition[] = registeredTours(
        inject(GUIDED_TOUR_FACTORIES, { optional: true }) ?? []
    );

    find(key: string): TourDefinition | null {
        return this.tours.find((tour) => tour.key === key) ?? null;
    }
}

/**
 * Builds the tours and checks them. In dev mode (and specs) a mistake throws, so it is fixed before it ships. In
 * production it is logged and only the tours it concerns are left out (one whose factory throws, an invalid one, a
 * later one under a key already taken): a broken tour must not take the app down with it. Runs in an injection
 * context, which the factories need.
 */
function registeredTours(factories: readonly TourDefinitionFactory[]): readonly TourDefinition[] {
    const built = factories.flatMap((factory, index) => {
        try {
            return [factory()];
        } catch (error: unknown) {
            if (isDevMode()) {
                throw error;
            }
            console.error(`[GuidedTour] Tour definition #${index + 1} failed to build and is left out:`, error);
            return [];
        }
    });
    const { validTours, problems } = validateTourDefinitions(built);
    if (problems.length > 0) {
        const message = `Invalid guided tour definitions:\n- ${problems.join('\n- ')}`;
        if (isDevMode()) {
            throw new Error(message);
        }
        console.error(`[GuidedTour] ${message}\nThe tours concerned are left out.`);
    }
    return validTours;
}
