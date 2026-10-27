import { computed } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from './config.service';

describe('ConfigService', () => {
    it('lets a computed made before the config loaded see the loaded config', async () => {
        const service = TestBed.inject(ConfigService);
        const config = computed(() => service.getConfig());
        expect(config()).toBeNull();

        await service.loadConfig();

        expect(config()).not.toBeNull();
    });
});
