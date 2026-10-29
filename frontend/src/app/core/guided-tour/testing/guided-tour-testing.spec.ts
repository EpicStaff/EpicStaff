import { FakeTourProgressStore } from './guided-tour-testing';
import { describeTourProgressStoreContract, TourProgressStoreHarness } from './tour-progress-store-contract';

describeTourProgressStoreContract('FakeTourProgressStore', (): TourProgressStoreHarness => {
    const store = new FakeTourProgressStore();
    let landHeldSaves = store.holdSaves();
    const settleHeldSaves = (): void => {
        landHeldSaves();
        landHeldSaves = store.holdSaves();
    };

    return {
        store,
        signIn: (userId, completedTourKeys) => store.signIn(userId, completedTourKeys),
        signOut: () => store.signOut(),
        landSaves: settleHeldSaves,
        refuseSaves: () => {
            store.failSaves = true;
            settleHeldSaves();
        },
    };
});
