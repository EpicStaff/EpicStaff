import {
    createPluginLogin,
    createPopupState,
    type EpicStaffPlugin,
    type PluginLogin,
    startPlugin,
} from '@epicstaff/plugin-sdk';

import type { ApiFetch } from './api';
import { checkAvailabilityAgain, MAINTENANCE_RETRY_MS, showsMaintenance } from './availability';
import { element } from './dom';
import { FORECAST_PATH, ForecastPage, requestedCity } from './forecast';
import {
    CONNECT_PATH,
    type ConnectState,
    maintenanceNote,
    OAUTH_CALLBACK_PATH,
    POPUP_RELAY_PATH,
    renderConnect,
    renderLoginState,
    renderPopupOutcome,
    renderWhoAmI,
    WHO_AM_I_PATH,
    type WhoAmI,
    type WhoAmIState,
} from './login-pages';
import { ORG_SETTINGS_PATH, ORG_SETTINGS_PERMISSION, OrgSettingsPage, type Permissions } from './org-settings';
import { ABOUT_PATH, renderAbout, renderNotFound } from './pages';
import { PLACES_PATH, PlacesPage } from './places';

interface NavigationEntry {
    path: string;
    label: string;
    /** Shown only to a person holding this permission on the plugin. */
    permission?: string;
}

const NAVIGATION: readonly NavigationEntry[] = [
    { path: FORECAST_PATH, label: 'Forecast' },
    { path: PLACES_PATH, label: 'Places' },
    { path: ORG_SETTINGS_PATH, label: 'Organization settings', permission: ORG_SETTINGS_PERMISSION },
    { path: WHO_AM_I_PATH, label: 'Who am I' },
    { path: CONNECT_PATH, label: 'Connect' },
    { path: ABOUT_PATH, label: 'About' },
];

/** The pages that need the person signed in. */
const SIGNED_IN_PATHS: readonly string[] = [FORECAST_PATH, PLACES_PATH, ORG_SETTINGS_PATH, WHO_AM_I_PATH, CONNECT_PATH];

/** The address the page starts on; it shows the forecast. */
const HOME_PATH = '/';

/**
 * The Weather page: routes kept in the address path. `startPlugin` runs before the first render, so it removes the
 * `es_org` hint before the router reads the address, and EpicStaff's address follows every route change from then on.
 * The person is signed in through EpicStaff right after; the page the demo provider returns to only hands the
 * provider's result back. Opened on its own while Weather is being updated, the page says so instead of its pages and
 * checks again every 30 seconds; inside EpicStaff, EpicStaff shows its own panel.
 */
async function main(): Promise<void> {
    const root = document.getElementById('app');
    if (!root) return;
    let plugin: EpicStaffPlugin;
    try {
        plugin = await startPlugin({ routing: 'pathname' });
    } catch (error) {
        root.replaceChildren(element('p', 'note', `Weather could not start: ${describe(error)}`));
        return;
    }

    if (location.pathname === OAUTH_CALLBACK_PATH) {
        await finishPopup(root, plugin);
        return;
    }

    let login: PluginLogin | null = null;
    let loginUnavailable = '';
    try {
        login = createPluginLogin(plugin);
    } catch (error) {
        loginUnavailable = `Signing in is not available here: ${describe(error)}`;
    }
    const pluginName = plugin.config.plugin.name;
    let whoAmI: WhoAmIState = { status: 'loading' };
    /** The token expiry the "Who am I" answer belongs to: a renewed token asks again. */
    let whoAmIExpiry: number | null = null;
    /** The permissions of the last answer, kept while a renewed token asks again. */
    let knownPermissions: readonly string[] | null = null;
    let connect: ConnectState = { status: 'idle' };
    // Built on first visit and kept, so what the person typed and the running forecast survive moving around.
    let forecastPage: ForecastPage | null = null;
    let placesPage: PlacesPage | null = null;
    let orgSettingsPage: OrgSettingsPage | null = null;
    /** The next check whether Weather is back, while the page says it is being updated. */
    let recheckTimer: ReturnType<typeof setTimeout> | null = null;

    // The header is built once and updated in place, so a re-render never takes the focus from a link in it.
    const signedInLine = element('span', 'muted');
    const nav = element('nav', 'nav');
    nav.setAttribute('aria-label', pluginName);
    const navLinks = NAVIGATION.map((entry) => {
        const link = element('a', null, entry.label);
        link.href = entry.path;
        nav.append(link);
        return { entry, link };
    });
    const title = element('div', 'title-block');
    title.append(element('h1', 'title', pluginName), signedInLine);
    const header = element('header', 'header');
    header.append(title, nav);
    const content = element('div', 'content');
    root.replaceChildren(header, content);

    const render = (): void => {
        if (location.pathname === HOME_PATH) history.replaceState(null, '', FORECAST_PATH);
        const path = location.pathname;
        if (login?.state === 'signed-in') askWhoAmI(login);
        updateHeader(path);
        const page = maintenancePage() ?? pageFor(path);
        // Re-inserting the same elements would take the focus from a field being typed in.
        const current = Array.from(content.children);
        if (current.length !== page.length || current.some((child, index) => child !== page[index])) {
            content.replaceChildren(...page);
        }
    };

    const updateHeader = (path: string): void => {
        for (const { entry, link } of navLinks) {
            link.hidden = entry.permission !== undefined && !knownPermissions?.includes(entry.permission);
            if (entry.path === path) link.setAttribute('aria-current', 'page');
            else link.removeAttribute('aria-current');
        }
        const signedIn = signedInAs();
        if (signedInLine.textContent !== signedIn) signedInLine.textContent = signedIn;
    };

    const signedInAs = (): string => {
        if (login === null) return 'Not signed in';
        const session = login.session;
        if (session !== null) return `${session.user.name} · ${session.org.name}`;
        return login.state === 'access-denied' ? 'No access' : 'Not signed in';
    };

    const permissions = (): Permissions => {
        if (knownPermissions !== null) return { status: 'known', actions: knownPermissions };
        return whoAmI.status === 'failed' ? { status: 'failed', message: whoAmI.message } : { status: 'loading' };
    };

    /** "Weather is being updated" while it is, with the next check planned; `null` otherwise. */
    const maintenancePage = (): HTMLElement[] | null => {
        if (login === null || !showsMaintenance(plugin.framed, login.availability)) return null;
        const signedIn = login;
        recheckTimer ??= setTimeout(() => {
            recheckTimer = null;
            void checkAvailabilityAgain(signedIn).finally(render);
        }, MAINTENANCE_RETRY_MS);
        return [maintenanceNote(pluginName)];
    };

    const pageFor = (path: string): HTMLElement[] => {
        if (path === ABOUT_PATH) return renderAbout(plugin);
        if (!SIGNED_IN_PATHS.includes(path)) return renderNotFound();
        if (login === null) return [element('p', 'note', loginUnavailable)];
        const signedIn = login;
        const notSignedIn = renderLoginState(signedIn, pluginName);
        if (notSignedIn !== null) return notSignedIn;
        const fetchApi: ApiFetch = (apiPath, init) => signedIn.fetch(apiPath, init);
        switch (path) {
            case FORECAST_PATH: {
                forecastPage ??= new ForecastPage(fetchApi, pluginName, render);
                const city = requestedCity(location.search);
                if (city !== null) {
                    // Taken once: a re-render keeps what the person typed since, and the next link here fills it again.
                    history.replaceState(null, '', FORECAST_PATH);
                    forecastPage.prefill(city);
                }
                forecastPage.update();
                return [forecastPage.root];
            }
            case PLACES_PATH:
                placesPage ??= new PlacesPage(fetchApi, pluginName, render);
                placesPage.update(permissions());
                return [placesPage.root];
            case ORG_SETTINGS_PATH:
                orgSettingsPage ??= new OrgSettingsPage(fetchApi, pluginName, render);
                orgSettingsPage.update(permissions());
                return [orgSettingsPage.root];
            case CONNECT_PATH:
                return renderConnect(connect, (severOpener) => connectWith(signedIn, severOpener));
            default:
                return renderWhoAmI(signedIn, whoAmI, () => void signedIn.renew());
        }
    };

    const askWhoAmI = (signedIn: PluginLogin): void => {
        const expiry = signedIn.session?.expiresAt ?? null;
        if (expiry === whoAmIExpiry) return;
        whoAmIExpiry = expiry;
        whoAmI = { status: 'loading' };
        void signedIn
            .fetch('/api/whoami')
            .then(async (response): Promise<WhoAmIState> => {
                if (!response.ok) return { status: 'failed', message: `The backend answered HTTP ${response.status}.` };
                return { status: 'loaded', body: (await response.json()) as WhoAmI };
            })
            .catch((error: unknown): WhoAmIState => ({ status: 'failed', message: describe(error) }))
            .then((next) => {
                if (whoAmIExpiry !== expiry) return;
                whoAmI = next;
                if (next.status === 'loaded') knownPermissions = next.body.permissions;
                render();
            });
    };

    /** Runs inside the click handler: the popup must open before anything waits. */
    const connectWith = (signedIn: PluginLogin, severOpener: boolean): void => {
        const session = signedIn.session;
        if (session === null) return;
        const label = severOpener ? 'Connect — provider severs the opener' : 'Connect';
        const state = createPopupState(session.org.id);
        const query = `state=${encodeURIComponent(state)}&coop=${severOpener ? 1 : 0}`;
        const result = signedIn.openPopup(`/api/demo-provider?${query}`, {
            state,
            relay: { statusPath: `${POPUP_RELAY_PATH}/${encodeURIComponent(state)}` },
        });
        connect = { status: 'waiting', label };
        render();
        result.then(
            (popupResult) => {
                connect = { status: 'done', label, result: popupResult };
                render();
            },
            (error: unknown) => {
                connect = { status: 'failed', label, message: describe(error) };
                render();
            }
        );
    };

    // In-app links change the route with pushState; the SDK reports the change to EpicStaff.
    root.addEventListener('click', (event) => {
        const link = event.target instanceof Element ? event.target.closest('a') : null;
        if (!link || link.origin !== location.origin || event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        const target = link.pathname + link.search;
        if (target !== location.pathname + location.search) history.pushState(null, '', target);
        render();
    });
    // EpicStaff's back/forward and links arrive as popstate (the SDK's default nav.navigate handling).
    window.addEventListener('popstate', render);
    plugin.onThemeChange(render);
    login?.onChange(render);
    login?.onAvailabilityChange((availability) => {
        // Back after an update: the list shown may be the refusal it got meanwhile.
        if (availability === 'available') placesPage?.refresh();
        render();
    });
    render();
    void login?.start();
}

/** The demo provider's return page: hands the provider's result to the page that opened the popup. */
async function finishPopup(root: HTMLElement, plugin: EpicStaffPlugin): Promise<void> {
    const pluginName = plugin.config.plugin.name;
    root.replaceChildren(...renderPopupOutcome(null, pluginName));
    try {
        const outcome = await createPluginLogin(plugin).completePopup({ relayPath: POPUP_RELAY_PATH });
        root.replaceChildren(...renderPopupOutcome(outcome, pluginName));
    } catch (error) {
        root.replaceChildren(element('p', 'note note--error', `Could not finish: ${describe(error)}`));
    }
}

function describe(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
}

void main();
