import { PROVIDER_ICON_PATHS, PROVIDER_MONOCHROME_ICON_PATHS } from '@shared/constants';

export function getProviderIconPath(providerName: string | undefined | null): string {
    if (!providerName) {
        return PROVIDER_ICON_PATHS['default'];
    }

    const normalizedName: string = providerName.toLowerCase();
    return PROVIDER_ICON_PATHS[normalizedName] || PROVIDER_ICON_PATHS['default'];
}

/** A provider's icon for a heading, and whether it is a multi-colour logo to be painted in the text colour. */
export interface ProviderHeadingIcon {
    icon: string;
    isTinted: boolean;
}

/** The provider's one-colour logo where it has one, else `fallbackIcon` (its own logo), tinted. */
export function getProviderHeadingIcon(providerId: string, fallbackIcon: string): ProviderHeadingIcon {
    const monochrome = PROVIDER_MONOCHROME_ICON_PATHS[providerId.toLowerCase()];
    return monochrome ? { icon: monochrome, isTinted: false } : { icon: fallbackIcon, isTinted: true };
}
