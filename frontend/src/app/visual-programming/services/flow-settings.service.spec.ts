import { TestBed } from '@angular/core/testing';

import { FlowSettingsService } from './flow-settings.service';

const STORAGE_KEY = 'flow-settings';

function createService(): FlowSettingsService {
    return TestBed.inject(FlowSettingsService);
}

function storedSettings(): Record<string, unknown> {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)!);
}

describe('FlowSettingsService always show node numbers', () => {
    beforeEach(() => localStorage.clear());

    it('is off by default', () => {
        expect(createService().alwaysShowNodeNumbers()).toBe(false);
    });

    it('persists the setting next to the other flow settings', () => {
        const service = createService();
        service.showInputsOutputs.set(true);

        service.alwaysShowNodeNumbers.set(true);
        TestBed.tick();

        expect(storedSettings()).toMatchObject({ alwaysShowNodeNumbers: true, showInputsOutputs: true });
    });

    it('loads the stored setting', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ alwaysShowNodeNumbers: true }));

        expect(createService().alwaysShowNodeNumbers()).toBe(true);
    });

    it.each(['true', 1, null, {}])('ignores a stored value that is not a boolean: %j', (stored) => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ alwaysShowNodeNumbers: stored }));

        expect(createService().alwaysShowNodeNumbers()).toBe(false);
    });
});
