import { TourProgressStore } from '../progress/tour-progress-store';

/** Acts on a TourProgressStore the way the app and the backend do, so one suite can hold every store to the contract. */
export interface TourProgressStoreHarness {
    readonly store: TourProgressStore;
    /** A user signs in, having completed `completedTourKeys` before. */
    signIn(userId: number, completedTourKeys: readonly string[]): void;
    signOut(): void;
    /** The backend stores each save on its way for the user who made it, and answers it. */
    landSaves(): void;
    /** The backend refuses each save on its way: the user already completed as many tours as it keeps. */
    refuseSaves(): void;
}

/**
 * What the engine relies on from a TourProgressStore, run against the real store and against the specs' fake, so the
 * fake cannot drift from it. `createHarness` runs in beforeEach, with saves held until the harness lands them.
 */
export function describeTourProgressStoreContract(name: string, createHarness: () => TourProgressStoreHarness): void {
    describe(`${name} (TourProgressStore contract)`, () => {
        let harness: TourProgressStoreHarness;

        beforeEach(() => {
            harness = createHarness();
        });

        function completedTourKeys(): string[] {
            return [...harness.store.completedTourKeys()].sort();
        }

        it('has no user and no completed tours while nobody is signed in', () => {
            expect(harness.store.userId()).toBeNull();
            expect(completedTourKeys()).toEqual([]);
        });

        it('reports the signed-in user and the tours they completed', () => {
            harness.signIn(7, ['quick-start', 'release-notes']);

            expect(harness.store.userId()).toBe(7);
            expect(completedTourKeys()).toEqual(['quick-start', 'release-notes']);
        });

        it('reports a tour completed once its save lands', () => {
            harness.signIn(7, ['quick-start']);
            const saved = vi.fn();

            harness.store.markCompleted('release-notes').subscribe(saved);
            expect(completedTourKeys()).toEqual(['quick-start']);
            harness.landSaves();

            expect(saved).toHaveBeenCalledTimes(1);
            expect(completedTourKeys()).toEqual(['quick-start', 'release-notes']);
        });

        it('succeeds, and still reports nothing, when the save lands after sign-out', () => {
            harness.signIn(7, []);
            const saved = vi.fn();

            harness.store.markCompleted('release-notes').subscribe(saved);
            harness.signOut();
            harness.landSaves();

            expect(saved).toHaveBeenCalledTimes(1);
            expect(harness.store.userId()).toBeNull();
            expect(completedTourKeys()).toEqual([]);
        });

        it('keeps the tours of another user who signed in while the save was on its way', () => {
            harness.signIn(7, []);

            harness.store.markCompleted('release-notes').subscribe();
            harness.signOut();
            harness.signIn(8, ['quick-start']);
            harness.landSaves();

            expect(harness.store.userId()).toBe(8);
            expect(completedTourKeys()).toEqual(['quick-start']);
        });

        it('fails, and leaves the tour not completed, when the save is refused', () => {
            harness.signIn(7, []);
            const failed = vi.fn();

            harness.store.markCompleted('release-notes').subscribe({ error: failed });
            harness.refuseSaves();

            expect(failed).toHaveBeenCalledTimes(1);
            expect(completedTourKeys()).toEqual([]);
        });
    });
}
