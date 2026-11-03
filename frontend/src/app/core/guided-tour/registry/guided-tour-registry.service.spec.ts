import { EnvironmentInjector, inject, InjectionToken } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { TourDefinition, TourStep } from '../model/tour-definition';
import { GuidedTourRegistry, TourDefinitionFactory } from './guided-tour-registry.service';
import { provideGuidedTours } from './provide-guided-tours';

function step(id: string): TourStep {
    return { id, content: { title: id, body: [] } };
}

function tour(key: string, steps: TourStep[] = [step('only')]): TourDefinition {
    return { key, label: key, icon: 'help', autoStart: 'manual', isAvailable: () => true, steps };
}

/** A tour factory with a bug in it. */
function failingFactory(): TourDefinition {
    throw new Error('The tour factory failed');
}

function register(...factories: TourDefinitionFactory[]): void {
    TestBed.configureTestingModule({ providers: [provideGuidedTours(...factories)] });
}

/** Starting the app: anything injected creates the environment, which runs its initializers. */
function startApp(): void {
    TestBed.inject(EnvironmentInjector);
}

/** Starts the app as a production build would (no dev mode), and returns the tours it registered. */
function startAppInProduction(): string[] {
    vi.stubGlobal('ngDevMode', false);
    try {
        return TestBed.inject(GuidedTourRegistry).tours.map((registered) => registered.key);
    } finally {
        vi.unstubAllGlobals();
    }
}

describe('GuidedTourRegistry', () => {
    it('keeps the tours in registration order and finds them by key', () => {
        register(
            () => tour('second-tour'),
            () => tour('first-tour')
        );
        const registry = TestBed.inject(GuidedTourRegistry);

        expect(registry.tours.map((registered) => registered.key)).toEqual(['second-tour', 'first-tour']);
        expect(registry.find('first-tour')?.key).toBe('first-tour');
        expect(registry.find('missing-tour')).toBeNull();
    });

    it('builds each tour in an injection context', () => {
        const LABEL = new InjectionToken<string>('LABEL', { factory: () => 'Injected label' });
        register(() => ({ ...tour('intro'), label: inject(LABEL) }));

        expect(TestBed.inject(GuidedTourRegistry).find('intro')?.label).toBe('Injected label');
    });

    describe('in dev mode (and specs)', () => {
        it('fails the app start with every problem listed in one error', () => {
            register(
                () => tour('Intro', []),
                () => tour('other', [step('same'), step('same')])
            );

            expect(startApp).toThrow(
                /Invalid guided tour definitions:[\s\S]*Tour key "Intro" must be[\s\S]*Tour "Intro" has no steps\.[\s\S]*Tour "other" has more than one step "same"\./
            );
        });

        it('fails the app start with the error of a tour factory that throws', () => {
            register(() => tour('intro'), failingFactory);

            expect(startApp).toThrow('The tour factory failed');
        });
    });

    describe('in production', () => {
        let consoleError: ReturnType<typeof vi.spyOn>;

        beforeEach(() => {
            consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        });
        afterEach(() => consoleError.mockRestore());

        it('starts, logging the problems, without the invalid tours and later tours under a taken key', () => {
            register(
                () => tour('first'),
                () => tour('invalid', []),
                () => tour('first', [step('other')]),
                () => tour('last')
            );

            expect(startAppInProduction()).toEqual(['first', 'last']);
            expect(consoleError).toHaveBeenCalledExactlyOnceWith(
                expect.stringMatching(/registered more than once[\s\S]*"invalid" has no steps/)
            );
        });

        it('starts, logging the error, without a tour whose factory throws', () => {
            register(failingFactory, () => tour('intro'));

            expect(startAppInProduction()).toEqual(['intro']);
            expect(consoleError).toHaveBeenCalledExactlyOnceWith(
                expect.stringContaining('Tour definition #1 failed to build'),
                expect.objectContaining({ message: 'The tour factory failed' })
            );
        });
    });
});
