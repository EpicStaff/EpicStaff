import { InjectionToken } from '@angular/core';

import { AuditEnumOption, AuditFilterNode, AuditFilterOp, AuditValuesFilter } from './audit-filter.models';

export type AuditDomainName = 'sessions' | 'user_actions';

// The distinct values the auditor recorded for one field of a domain.
export interface AuditFieldValues {
    field: string;
    values: string[];
}

// The titled part of the Builder a field shows in; the date closes the quick filters.
export type AuditBuilderSection = 'quick' | 'deep';

// The lists the tab loads: the org's records a lookup field picks from, and the values recorded for a select
// field that only the auditor knows. A list that fails to load is empty.
export type AuditLookupSource = 'flows' | 'members' | 'targetTypes';
export type AuditLookupOptions = Partial<Record<AuditLookupSource, AuditEnumOption[]>>;

// A Builder filter picked from a list of values: `field in (...)` / `field not in (...)`. The list is fixed
// (`options`), or the tab loads it from `source`.
export type AuditSelectField = {
    kind: 'select';
    field: string;
    label: string;
    section: AuditBuilderSection;
} & ({ options: AuditEnumOption[] } | { source: AuditLookupSource });

// A Builder filter of typed conditions on one text field, offering only `operators`.
export interface AuditTextField {
    kind: 'text';
    field: string;
    label: string;
    section: AuditBuilderSection;
    operators: AuditFilterOp[];
}

// A Builder filter picked by id from the org's live records, labelled with their current names.
// `field` keys its selection and chip; `compile` turns the picked ids into the filter it sends.
export interface AuditLookupField {
    kind: 'lookup';
    field: string;
    label: string;
    section: AuditBuilderSection;
    source: AuditLookupSource;
    compile: (selection: AuditValuesFilter) => AuditFilterNode;
}

export type AuditCatalogField = AuditSelectField | AuditTextField | AuditLookupField;

// The values a select or lookup field offers, from its fixed options or the loaded `lists`.
export function catalogFieldOptions(
    builderField: AuditSelectField | AuditLookupField,
    lists: AuditLookupOptions
): AuditEnumOption[] {
    return 'options' in builderField ? builderField.options : (lists[builderField.source] ?? []);
}

// What one audit domain can be filtered by. The sessions Builder is its own fixed set of filters with a
// match scope, so its catalog lists no builderFields; every other domain declares its Builder here.
export interface AuditFieldCatalog {
    domain: AuditDomainName;
    builderFields: AuditCatalogField[];
    queryFields: string[];
    queryExamples: string[];
    queryPlaceholder: string;
}

// Provided by each audit tab, so its filters panel, presets and preset storage all work in that tab's domain.
export const AUDIT_FIELD_CATALOG = new InjectionToken<AuditFieldCatalog>('AUDIT_FIELD_CATALOG');
