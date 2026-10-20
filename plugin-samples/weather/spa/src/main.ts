import { type EpicStaffPlugin, startPlugin } from '@epicstaff/plugin-sdk';

import { element } from './dom';
import { ABOUT_PATH, FORECAST_PATH, renderAbout, renderForecast, renderNotFound } from './pages';

const NAVIGATION: readonly (readonly [string, string])[] = [
    [FORECAST_PATH, 'Forecast'],
    [ABOUT_PATH, 'About'],
];

/**
 * The Weather page: two routes kept in the address path. `startPlugin` runs before the first render, so it removes the
 * `es_org` hint before the router reads the address, and EpicStaff's address follows every route change from then on.
 */
async function main(): Promise<void> {
    const root = document.getElementById('app');
    if (!root) return;
    let plugin: EpicStaffPlugin;
    try {
        plugin = await startPlugin({ routing: 'pathname' });
    } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        root.replaceChildren(element('p', 'note', `Weather could not start: ${reason}`));
        return;
    }

    const render = (): void => {
        const path = location.pathname;
        const header = element('header', 'header');
        const nav = element('nav', 'nav');
        nav.setAttribute('aria-label', 'Weather');
        for (const [href, label] of NAVIGATION) {
            const link = element('a', null, label);
            link.href = href;
            if (href === path) link.setAttribute('aria-current', 'page');
            nav.append(link);
        }
        header.append(element('h1', 'title', plugin.config.plugin.name), nav);
        const content = pageFor(path);
        root.replaceChildren(header, ...content);
    };

    const pageFor = (path: string): HTMLElement[] => {
        if (path === FORECAST_PATH) return renderForecast();
        if (path === ABOUT_PATH) return renderAbout(plugin);
        return renderNotFound();
    };

    // In-app links change the route with pushState; the SDK reports the change to EpicStaff.
    root.addEventListener('click', (event) => {
        const link = event.target instanceof Element ? event.target.closest('a') : null;
        if (!link || link.origin !== location.origin || event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        if (link.pathname !== location.pathname) history.pushState(null, '', link.pathname);
        render();
    });
    // EpicStaff's back/forward and links arrive as popstate (the SDK's default nav.navigate handling).
    window.addEventListener('popstate', render);
    plugin.onThemeChange(render);
    render();
}

void main();
