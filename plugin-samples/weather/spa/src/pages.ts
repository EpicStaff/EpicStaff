import type { EpicStaffPlugin } from '@epicstaff/plugin-sdk';

import { element, facts } from './dom';
import { SAMPLE_PLACES } from './places';

export const FORECAST_PATH = '/';
export const ABOUT_PATH = '/about';

/** The forecast page: the sample places. */
export function renderForecast(): HTMLElement[] {
    const note = element(
        'p',
        'note',
        'Sample data. The sample’s backend tells who is signed in (Who am I), not forecasts.'
    );
    const list = element('ul', 'places');
    for (const place of SAMPLE_PLACES) {
        const item = element('li', 'place');
        item.append(
            element('span', 'place-name', place.name),
            element('span', 'place-temperature', `${place.temperatureCelsius} °C`),
            element('span', 'muted', place.summary)
        );
        list.append(item);
    }
    return [note, list];
}

/** The about page: what the platform told the page, to see the frame protocol at work. */
export function renderAbout(plugin: EpicStaffPlugin): HTMLElement[] {
    const { name, version, identifier } = plugin.config.plugin;
    const organization = plugin.org?.name ?? (plugin.orgHint === null ? 'None' : `Organization ${plugin.orgHint}`);
    return [
        facts([
            ['Plugin', `${name} ${version} (${identifier})`],
            ['Running', plugin.framed ? 'Inside EpicStaff' : `On its own (${plugin.unframedReason ?? 'not framed'})`],
            ['Organization', organization],
            ['Theme', plugin.theme()?.mode ?? 'Default'],
            ['EpicStaff', plugin.config.epicstaff_origin],
        ]),
    ];
}

export function renderNotFound(): HTMLElement[] {
    return [element('p', 'muted', 'There is no such page in Weather.')];
}
