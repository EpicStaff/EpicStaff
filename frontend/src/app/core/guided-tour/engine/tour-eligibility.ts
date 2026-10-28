import { TourDefinition } from '../model/tour-definition';

export type AutoStartCandidate = Pick<TourDefinition, 'key' | 'autoStart'>;

/**
 * The first tour, in registry order, that should start by itself now: an auto-start tour the user has not completed,
 * that has not been handled yet, and that the user can take (`isAvailable`). Null when there is none. Availability is
 * checked last and only as far as needed, so a reactive caller re-runs on the availability of the tours that are
 * still in question.
 */
export function findAutoStartTour<Tour extends AutoStartCandidate>(
    tours: readonly Tour[],
    completedTourKeys: ReadonlySet<string>,
    handledTourKeys: ReadonlySet<string>,
    isAvailable: (tour: Tour) => boolean
): Tour | null {
    return (
        tours.find(
            (tour) =>
                tour.autoStart === 'until-completed' &&
                !completedTourKeys.has(tour.key) &&
                !handledTourKeys.has(tour.key) &&
                isAvailable(tour)
        ) ?? null
    );
}
