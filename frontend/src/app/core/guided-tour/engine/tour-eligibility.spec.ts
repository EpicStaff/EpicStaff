import { TourAutoStart } from '../model/tour-definition';
import { AutoStartCandidate, findAutoStartTour } from './tour-eligibility';

interface Candidate extends AutoStartCandidate {
    readonly isAvailable: boolean;
}

function tour(key: string, autoStart: TourAutoStart = 'until-completed', isAvailable = true): Candidate {
    return { key, autoStart, isAvailable };
}

describe('findAutoStartTour', () => {
    it.each<[description: string, tours: Candidate[], completed: string[], handled: string[], expected: string | null]>(
        [
            ['starts an auto-start tour the user has not completed', [tour('intro')], [], [], 'intro'],
            ['never starts a manual tour', [tour('intro', 'manual')], [], [], null],
            ['skips a completed tour', [tour('intro')], ['intro'], [], null],
            ['skips a tour already handled for this user', [tour('intro')], [], ['intro'], null],
            ['skips a tour the user cannot take', [tour('intro', 'until-completed', false)], [], [], null],
            ['takes the first eligible tour in registry order', [tour('first'), tour('second')], [], [], 'first'],
            [
                'passes over ineligible tours to the next eligible one',
                [tour('manual', 'manual'), tour('done'), tour('unavailable', 'until-completed', false), tour('next')],
                ['done'],
                [],
                'next',
            ],
            ['finds nothing among no tours', [], [], [], null],
        ]
    )('%s', (_description, tours, completed, handled, expected) => {
        const found = findAutoStartTour(tours, new Set(completed), new Set(handled), (tour) => tour.isAvailable);

        expect(found?.key ?? null).toBe(expected);
    });
});
