import { InjectionToken } from '@angular/core';

import { AuditEnumOption, AuditFilterOp } from './audit-filter.models';

export type AuditDomainName = 'sessions' | 'user_actions';

// A Builder filter picked from a fixed list of values: `field in (...)` / `field not in (...)`.
export interface AuditSelectField {
    kind: 'select';
    field: string;
    label: string;
    options: AuditEnumOption[];
}

// A Builder filter of typed conditions on one text field, offering only `operators`.
export interface AuditTextField {
    kind: 'text';
    field: string;
    label: string;
    operators: AuditFilterOp[];
}

export type AuditCatalogField = AuditSelectField | AuditTextField;

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
