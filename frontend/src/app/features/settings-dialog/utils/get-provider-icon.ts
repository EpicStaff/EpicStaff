import { PROVIDER_ICON_PATHS } from '../constants/provider-icons.constants';

export function getProviderIconPath(
  providerName: string | undefined | null
): string {
  if (!providerName) {
    return PROVIDER_ICON_PATHS['default'];
  }

  const normalizedName: string = providerName.toLowerCase();
  return PROVIDER_ICON_PATHS[normalizedName] || PROVIDER_ICON_PATHS['default'];
}
