import { TestBed } from '@angular/core/testing';
import { ORG_SWITCH_URL_RULES } from '@shared/services';

import { providePluginsExtensions } from '../plugins.providers';
import { pluginRootUrl } from './plugin-root-url.util';

describe('pluginRootUrl', () => {
    it.each([
        ['/plugins/weather', '/plugins/weather'],
        ['/plugins/weather/forecast/berlin?days=3#top', '/plugins/weather'],
        ['/plugins/weather?city=Rome', '/plugins/weather'],
        ['/plugins/weather;x=1/forecast', '/plugins/weather'],
    ])('keeps only the plugin of %s', (url, root) => {
        expect(pluginRootUrl(url)).toBe(root);
    });

    it.each(['/plugins', '/plugins/', '/pluginsx/weather', '/workspace/plugins/weather', '/flows/12'])(
        'leaves %s to the other rules',
        (url) => {
            expect(pluginRootUrl(url)).toBeNull();
        }
    );

    it('is the organization-switch rule the plugin feature registers', () => {
        TestBed.configureTestingModule({ providers: [providePluginsExtensions()] });

        expect(TestBed.inject(ORG_SWITCH_URL_RULES)).toEqual([pluginRootUrl]);
    });
});
