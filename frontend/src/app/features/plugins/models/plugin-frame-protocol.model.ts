import { PLUGIN_FRAME_AVAILABILITY_STATES, PLUGIN_THEME_MODES } from '../constants/plugin-frame-protocol.constants';

export type PluginThemeMode = (typeof PLUGIN_THEME_MODES)[number];

/** A framed plugin page's view of its own API; never trusted, only a reason to ask EpicStaff's server again. */
export type PluginFrameAvailability = (typeof PLUGIN_FRAME_AVAILABILITY_STATES)[number];

/** EpicStaff's theme as a plugin page sees it: the mode and the `--es-*` tokens EpicStaff defines. */
export interface PluginTheme {
    mode: PluginThemeMode;
    tokens: Readonly<Record<string, string>>;
}

/** The organization a plugin page is opened in. */
export interface PluginFrameOrg {
    id: number;
    name: string;
}

export interface PluginFrameInitMessage {
    type: 'es:init';
    protocol: number;
    theme: PluginTheme;
    nav: { path: string };
    org: PluginFrameOrg;
}

export interface PluginFrameErrorMessage {
    type: 'es:error';
    protocol: number;
    code: 'unsupported_protocol';
}

export interface PluginNavNavigateMessage {
    type: 'nav.navigate';
    path: string;
}

export interface PluginThemeChangedMessage {
    type: 'theme.changed';
    theme: PluginTheme;
}
