import {
    EASTER_EGG_MAX_CLICK_GAP_MS,
    EASTER_EGG_REQUIRED_CLICKS,
    EasterEggTriggerService,
} from './easter-egg-trigger.service';

describe('EasterEggTriggerService', () => {
    let service: EasterEggTriggerService;
    let activationCount: number;

    beforeEach(() => {
        service = new EasterEggTriggerService();
        activationCount = 0;
        service.activated$.subscribe(() => activationCount++);
    });

    function clickRapidly(times: number, startMs: number, gapMs = 100): number {
        let timestamp = startMs;
        for (let click = 0; click < times; click++) {
            service.registerLogoClick(timestamp);
            timestamp += gapMs;
        }
        return timestamp - gapMs;
    }

    it('activates on the seventh rapid click', () => {
        clickRapidly(EASTER_EGG_REQUIRED_CLICKS - 1, 0);
        expect(activationCount).toBe(0);

        service.registerLogoClick((EASTER_EGG_REQUIRED_CLICKS - 1) * 100);
        expect(activationCount).toBe(1);
    });

    it('restarts the streak after a slow click', () => {
        const lastTimestamp = clickRapidly(EASTER_EGG_REQUIRED_CLICKS - 1, 0);
        service.registerLogoClick(lastTimestamp + EASTER_EGG_MAX_CLICK_GAP_MS);
        expect(activationCount).toBe(0);

        clickRapidly(EASTER_EGG_REQUIRED_CLICKS - 2, lastTimestamp + EASTER_EGG_MAX_CLICK_GAP_MS + 100);
        expect(activationCount).toBe(0);

        service.registerLogoClick(lastTimestamp + EASTER_EGG_MAX_CLICK_GAP_MS + 100 * EASTER_EGG_REQUIRED_CLICKS);
        expect(activationCount).toBe(1);
    });

    it('accepts a gap just under the limit', () => {
        clickRapidly(EASTER_EGG_REQUIRED_CLICKS, 0, EASTER_EGG_MAX_CLICK_GAP_MS - 1);
        expect(activationCount).toBe(1);
    });

    it('needs a fresh streak of seven clicks after activating', () => {
        const lastTimestamp = clickRapidly(EASTER_EGG_REQUIRED_CLICKS, 0);
        expect(activationCount).toBe(1);

        clickRapidly(EASTER_EGG_REQUIRED_CLICKS - 1, lastTimestamp + 100);
        expect(activationCount).toBe(1);
    });
});
