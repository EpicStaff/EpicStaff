import { SideSectionNavItem } from '@shared/components';

/** The settings page's left menu, in the order shown. Each entry is a child route of `/profile/settings`. */
export const SETTINGS_SECTIONS: SideSectionNavItem[] = [
    { route: 'general', label: 'General', icon: 'ti-settings' },
    { route: 'flow-editor', label: 'Flow editor', icon: 'ti-route' },
    { route: 'shortcuts', label: 'Shortcuts', icon: 'ti-keyboard' },
];
