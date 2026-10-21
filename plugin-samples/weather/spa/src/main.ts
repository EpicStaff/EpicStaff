import {
    createPluginLogin,
    createPopupState,
    type EpicStaffPlugin,
    type PluginLogin,
    startPlugin,
} from '@epicstaff/plugin-sdk';

import { element } from './dom';
import {
    CONNECT_PATH,
    type ConnectState,
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
import { ABOUT_PATH, FORECAST_PATH, renderAbout, renderForecast, renderNotFound } from './pages';

const NAVIGATION: readonly (readonly [string, string])[] = [
    [FORECAST_PATH, 'Forecast'],
    [WHO_AM_I_PATH, 'Who am I'],
    [CONNECT_PATH, 'Connect'],
    [ABOUT_PATH, 'About'],
];

/**
 * The Weather page: routes kept in the address path. `startPlugin` runs before the first render, so it removes the
 * `es_org` hint before the router reads the address, and EpicStaff's address follows every route change from then on.
 * The person is signed in through EpicStaff right after; the page the demo provider returns to only hands the
 * provider's result back.
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
    let connect: ConnectState = { status: 'idle' };

    const render = (): void => {
        const path = location.pathname;
        const header = element('header', 'header');
        const nav = element('nav', 'nav');
        nav.setAttribute('aria-label', pluginName);
        for (const [href, label] of NAVIGATION) {
            const link = element('a', null, label);
            link.href = href;
            if (href === path) link.setAttribute('aria-current', 'page');
            nav.append(link);
        }
        const title = element('div', 'title-block');
        title.append(element('h1', 'title', pluginName), element('span', 'muted', signedInAs()));
        header.append(title, nav);
        root.replaceChildren(header, ...pageFor(path));
    };

    const signedInAs = (): string => {
        if (login === null) return 'Not signed in';
        const session = login.session;
        if (session !== null) return `${session.user.name} · ${session.org.name}`;
        return login.state === 'access-denied' ? 'No access' : 'Not signed in';
    };

    const pageFor = (path: string): HTMLElement[] => {
        if (path === FORECAST_PATH) return renderForecast();
        if (path === ABOUT_PATH) return renderAbout(plugin);
        if (path !== WHO_AM_I_PATH && path !== CONNECT_PATH) return renderNotFound();
        if (login === null) return [element('p', 'note', loginUnavailable)];
        const signedIn = login;
        const notSignedIn = renderLoginState(signedIn, pluginName);
        if (notSignedIn !== null) return notSignedIn;
        if (path === CONNECT_PATH) return renderConnect(connect, (severOpener) => connectWith(signedIn, severOpener));
        askWhoAmI(signedIn);
        return renderWhoAmI(signedIn, whoAmI, () => void signedIn.renew());
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
        if (link.pathname !== location.pathname) history.pushState(null, '', link.pathname);
        render();
    });
    // EpicStaff's back/forward and links arrive as popstate (the SDK's default nav.navigate handling).
    window.addEventListener('popstate', render);
    plugin.onThemeChange(render);
    login?.onChange(render);
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
