import { PROVIDER_DISPLAY_NAMES } from '@shared/constants';

/** A provider's UI name: its brand name when known, else the id with separators as spaces and each word capitalised. */
export function providerDisplayName(providerId: string): string {
    const known = PROVIDER_DISPLAY_NAMES[providerId.toLowerCase()];
    if (known) return known;
    return providerId
        .split(/[-_\s]+/)
        .filter((word) => word.length > 0)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}
