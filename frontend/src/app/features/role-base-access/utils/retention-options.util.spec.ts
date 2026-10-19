import { OrganizationRetention, OrganizationRetentionUpdate, RetentionPolicy } from '@shared/models';

import {
    buildRetentionItems,
    buildRetentionUpdate,
    describeRetentionLowerings,
    findRetentionLowerings,
    RetentionLowering,
} from './retention-options.util';

const POLICY: RetentionPolicy = {
    sessions: { default_days: 30, max_days: null, allowed: [30, 90, 180, 365, 0] },
    conversations: { default_days: 90, max_days: 180, allowed: [30, 90, 180] },
    audit: { default_days: 0, max_days: null, allowed: [30, 90, 180, 365, 0] },
};

function retention(overrides: Partial<OrganizationRetention> = {}): OrganizationRetention {
    return {
        org_id: 5,
        sessions_days: 90,
        sessions_effective_days: 90,
        conversations_days: null,
        conversations_effective_days: 90,
        audit_days: null,
        audit_effective_days: 0,
        updated_at: null,
        updated_by: null,
        retention_policy: POLICY,
        ...overrides,
    };
}

describe('findRetentionLowerings', () => {
    it.each<[string, Partial<OrganizationRetention>, OrganizationRetentionUpdate | null, RetentionLowering[]]>([
        [
            'warns when a finite value replaces unlimited',
            { sessions_days: 0, sessions_effective_days: 0 },
            { sessions_days: 365 },
            [{ type: 'sessions', newEffectiveDays: 365 }],
        ],
        [
            'warns when a finite value is lowered',
            {},
            { sessions_days: 30 },
            [{ type: 'sessions', newEffectiveDays: 30 }],
        ],
        ['does not warn when unlimited replaces a finite value', {}, { sessions_days: 0 }, []],
        [
            'warns when "Use default" brings in a default below the current effective value',
            {},
            { sessions_days: null },
            [{ type: 'sessions', newEffectiveDays: 30 }],
        ],
        [
            'does not warn when a value stored above the cap is set to the cap that is already applied',
            { conversations_days: 365, conversations_effective_days: 180 },
            { conversations_days: 180 },
            [],
        ],
        ['never warns for audit events', {}, { audit_days: 30 }, []],
        ['does not warn when nothing changed', {}, null, []],
        [
            'does not warn when the new value equals the current effective value',
            { sessions_days: null, sessions_effective_days: 30 },
            { sessions_days: 30 },
            [],
        ],
        [
            'lists every lowered type',
            {},
            { sessions_days: 30, conversations_days: 30 },
            [
                { type: 'sessions', newEffectiveDays: 30 },
                { type: 'conversations', newEffectiveDays: 30 },
            ],
        ],
    ])('%s', (_case, current, update, expected) => {
        expect(findRetentionLowerings(retention(current), update)).toEqual(expected);
    });
});

describe('describeRetentionLowerings', () => {
    it.each<[string, RetentionLowering[], string]>([
        [
            'names the single lowered type',
            [{ type: 'sessions', newEffectiveDays: 30 }],
            'Sessions older than 30 days will be removed tonight. This cannot be undone.',
        ],
        [
            'names both lowered types',
            [
                { type: 'sessions', newEffectiveDays: 30 },
                { type: 'conversations', newEffectiveDays: 90 },
            ],
            'Sessions older than 30 days and conversations older than 90 days will be removed tonight. This cannot be undone.',
        ],
    ])('%s', (_case, lowerings, expected) => {
        expect(describeRetentionLowerings(lowerings)).toBe(expected);
    });
});

describe('buildRetentionUpdate', () => {
    it('includes only the changed types', () => {
        expect(
            buildRetentionUpdate(retention(), { sessions_days: 90, conversations_days: 'default', audit_days: 30 })
        ).toEqual({ audit_days: 30 });
    });

    it('sends "Use default" as null', () => {
        expect(
            buildRetentionUpdate(retention(), {
                sessions_days: 'default',
                conversations_days: 'default',
                audit_days: 'default',
            })
        ).toEqual({ sessions_days: null });
    });

    it('returns null when nothing changed', () => {
        expect(
            buildRetentionUpdate(retention(), {
                sessions_days: 90,
                conversations_days: 'default',
                audit_days: 'default',
            })
        ).toBeNull();
    });
});

describe('buildRetentionItems', () => {
    it('starts with the default in days, then the allowed values in policy order', () => {
        expect(buildRetentionItems(retention(), 'sessions')).toEqual([
            { name: 'Use default (30 days)', value: 'default' },
            { name: '30 days', value: 30 },
            { name: '90 days', value: 90 },
            { name: '180 days', value: 180 },
            { name: '1 year', value: 365 },
            { name: 'Unlimited', value: 0 },
        ]);
    });

    it('labels an unlimited default as Unlimited', () => {
        expect(buildRetentionItems(retention(), 'audit')[0]).toEqual({
            name: 'Use default (Unlimited)',
            value: 'default',
        });
    });

    it('keeps a stored value above the cap as the last option, with the days applied', () => {
        const items = buildRetentionItems(
            retention({ conversations_days: 365, conversations_effective_days: 180 }),
            'conversations'
        );

        expect(items.at(-1)).toEqual({ name: '1 year (above limit, 180 days applied)', value: 365 });
    });
});
