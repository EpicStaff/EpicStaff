import { TourDefinition, TourStep } from '../model/tour-definition';
import { validateTourDefinitions } from './validate-tour-definitions';

const KEY_RULE = 'lowercase letters and digits in words joined by single hyphens, at most 64 characters';

function step(id: string, overrides: Partial<TourStep> = {}): TourStep {
    return { id, content: { title: id, body: [] }, ...overrides };
}

function tour(key: string, steps: TourStep[] = [step('only')]): TourDefinition {
    return { key, label: key, icon: 'help', autoStart: 'manual', isAvailable: () => true, steps };
}

/** A tour with one step, `only`, as given. */
function tourWithStep(overrides: Partial<TourStep>): TourDefinition {
    return tour('intro', [step('only', overrides)]);
}

describe('validateTourDefinitions', () => {
    it.each<[description: string, tours: TourDefinition[]]>([
        ['a key of one word', [tour('intro')]],
        ['a key of words and digits joined by hyphens', [tour('quick-start-2')]],
        ['a key of 64 characters', [tour('a'.repeat(64))]],
        [
            'Back to a step of the same tour',
            [tour('intro', [step('welcome'), step('done', { back: { toStep: 'welcome' } })])],
        ],
        [
            'an anchor that follows the key rule',
            [tourWithStep({ target: { anchor: 'sidenav-settings', side: 'right' } })],
        ],
        [
            'a click on the target as the only way on',
            [
                tourWithStep({
                    target: { anchor: 'opener', side: 'bottom' },
                    advance: { kind: 'target-click', timing: 'after-target' },
                    buttons: { next: false },
                }),
            ],
        ],
        [
            'an anchor appearing as the only way on',
            [tourWithStep({ advance: { kind: 'anchor-appears', anchor: 'result' }, buttons: { next: false } })],
        ],
        [
            'a navigation started only by a click on the target',
            [
                tourWithStep({
                    target: { anchor: 'settings-link', side: 'right' },
                    advance: { kind: 'navigation', url: '/settings', onTargetClick: true },
                    buttons: { next: false },
                }),
            ],
        ],
        [
            'following navigations into a section that contains the URL',
            [
                tourWithStep({
                    advance: {
                        kind: 'navigation',
                        url: '/settings/quickstart?tab=1',
                        followNavigationsInto: '/settings',
                    },
                }),
            ],
        ],
        [
            'following navigations into the URL itself',
            [tourWithStep({ advance: { kind: 'navigation', url: '/settings', followNavigationsInto: '/settings' } })],
        ],
    ])('accepts %s', (_description, tours) => {
        expect(validateTourDefinitions(tours)).toEqual({ validTours: tours, problems: [] });
    });

    it.each<[description: string, tours: [TourDefinition], problem: string]>([
        ['a key of 65 characters', [tour('a'.repeat(65))], `Tour key "${'a'.repeat(65)}" must be ${KEY_RULE}.`],
        ['a key with an uppercase letter', [tour('Quick-start')], `Tour key "Quick-start" must be ${KEY_RULE}.`],
        ['a key with an underscore', [tour('quick_start')], `Tour key "quick_start" must be ${KEY_RULE}.`],
        ['a key with a space', [tour('quick start')], `Tour key "quick start" must be ${KEY_RULE}.`],
        ['a key with a leading hyphen', [tour('-quick')], `Tour key "-quick" must be ${KEY_RULE}.`],
        ['a key with a trailing hyphen', [tour('quick-')], `Tour key "quick-" must be ${KEY_RULE}.`],
        ['a key with two hyphens in a row', [tour('quick--start')], `Tour key "quick--start" must be ${KEY_RULE}.`],
        ['an empty key', [tour('')], `Tour key "" must be ${KEY_RULE}.`],
        ['a tour without steps', [tour('intro', [])], 'Tour "intro" has no steps.'],
        [
            'two steps with one id',
            [tour('intro', [step('welcome'), step('welcome')])],
            'Tour "intro" has more than one step "welcome".',
        ],
        [
            'Back to a step that does not exist',
            [tour('intro', [step('welcome'), step('done', { back: { toStep: 'missing' } })])],
            'Step "done" of tour "intro" goes back to an unknown step "missing".',
        ],
        [
            'a target anchor outside the key rule',
            [tourWithStep({ target: { anchor: 'Settings Icon', side: 'right' } })],
            `Step "only" of tour "intro" has the anchor "Settings Icon", which must be ${KEY_RULE}.`,
        ],
        [
            'an awaited anchor that would break its selector',
            [tourWithStep({ advance: { kind: 'anchor-appears', anchor: 'card"]' } })],
            `Step "only" of tour "intro" has the anchor "card"]", which must be ${KEY_RULE}.`,
        ],
        [
            'a click advance without a target',
            [tourWithStep({ advance: { kind: 'target-click', timing: 'before-target' } })],
            'Step "only" of tour "intro" moves on by a click on its target, but has no target.',
        ],
        [
            'a navigation on a target click without a target',
            [tourWithStep({ advance: { kind: 'navigation', url: '/settings', onTargetClick: true } })],
            'Step "only" of tour "intro" moves on by a click on its target, but has no target.',
        ],
        [
            'Next hidden on a step that only Next moves on',
            [tourWithStep({ buttons: { next: false } })],
            'Step "only" of tour "intro" hides Next, and nothing else moves it on.',
        ],
        [
            'Next hidden on a step whose advance is Next',
            [tourWithStep({ advance: { kind: 'next' }, buttons: { next: false } })],
            'Step "only" of tour "intro" hides Next, and nothing else moves it on.',
        ],
        [
            'Next hidden on a navigation step the target cannot start',
            [tourWithStep({ advance: { kind: 'navigation', url: '/settings' }, buttons: { next: false } })],
            'Step "only" of tour "intro" hides Next, and nothing else moves it on.',
        ],
        [
            'following navigations into a section that does not contain the URL',
            [
                tourWithStep({
                    advance: { kind: 'navigation', url: '/settings/quickstart', followNavigationsInto: '/agents' },
                }),
            ],
            'Step "only" of tour "intro" follows navigations into "/agents", which does not contain its URL "/settings/quickstart".',
        ],
        [
            'following navigations into a page under the URL rather than around it',
            [
                tourWithStep({
                    advance: { kind: 'navigation', url: '/settings', followNavigationsInto: '/settings/quickstart' },
                }),
            ],
            'Step "only" of tour "intro" follows navigations into "/settings/quickstart", which does not contain its URL "/settings".',
        ],
    ])('reports %s, and leaves the tour out', (_description, tours, problem) => {
        expect(validateTourDefinitions(tours)).toEqual({ validTours: [], problems: [problem] });
    });

    it('keeps the valid tours in order, leaving out only the invalid ones and later tours under a taken key', () => {
        const first = tour('first');
        const invalid = tour('invalid', []);
        const laterDuplicate = tour('first', [step('other')]);
        const last = tour('last');

        const { validTours, problems } = validateTourDefinitions([first, invalid, laterDuplicate, last]);

        expect(validTours).toHaveLength(2);
        expect(validTours[0]).toBe(first);
        expect(validTours[1]).toBe(last);
        expect(problems).toEqual(['Tour key "first" is registered more than once.', 'Tour "invalid" has no steps.']);
    });

    it('lists every problem of every tour', () => {
        const { problems } = validateTourDefinitions([tour('Intro', []), tour('other', [step('same'), step('same')])]);

        expect(problems).toEqual([
            `Tour key "Intro" must be ${KEY_RULE}.`,
            'Tour "Intro" has no steps.',
            'Tour "other" has more than one step "same".',
        ]);
    });
});
