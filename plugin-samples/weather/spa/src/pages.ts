import type { EpicStaffPlugin } from '@epicstaff/plugin-sdk';

import { element, facts } from './dom';

export const ABOUT_PATH = '/about';

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
