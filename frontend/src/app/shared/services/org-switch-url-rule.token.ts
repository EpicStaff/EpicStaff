import { InjectionToken } from '@angular/core';

/**
 * Where to go after an organization switch, for the addresses one feature owns: the address to open in the new
 * organization, or `null` when the address is not the feature's. Page paths that hold data of the old organization
 * must not be kept.
 */
export type OrgSwitchUrlRule = (url: string) => string | null;

/**
 * Every feature's organization-switch rule (multi provider), so the organization menu maps a feature's addresses
 * without knowing the feature. The first rule that answers wins; without one the address is kept.
 */
export const ORG_SWITCH_URL_RULES = new InjectionToken<readonly OrgSwitchUrlRule[]>('ORG_SWITCH_URL_RULES');
