import { TestBed } from '@angular/core/testing';

import { FlowSettingsService } from './flow-settings.service';

const STORAGE_KEY = 'flow-settings';

function createService(): FlowSettingsService {
    return TestBed.inject(FlowSettingsService);
}

function storedSettings(): Record<string, unknown> {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)!);
}

describe('FlowSettingsService show node numbers in titles', () => {
    beforeEach(() => localStorage.clear());

    it('is off by default', () => {
        expect(createService().showNodeNumbersInTitles()).toBe(false);
    });

    it('persists the setting next to the other flow settings', () => {
        const service = createService();
        service.showInputsOutputs.set(true);

        service.showNodeNumbersInTitles.set(true);
        TestBed.tick();

        expect(storedSettings()).toMatchObject({ showNodeNumbersInTitles: true, showInputsOutputs: true });
    });

    it('loads the stored setting', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ showNodeNumbersInTitles: true }));

        expect(createService().showNodeNumbersInTitles()).toBe(true);
    });

    it.each(['true', 1, null, {}])('ignores a stored value that is not a boolean: %j', (stored) => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ showNodeNumbersInTitles: stored }));

        expect(createService().showNodeNumbersInTitles()).toBe(false);
    });
});
