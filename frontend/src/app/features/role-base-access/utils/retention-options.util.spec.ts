import { OrganizationRetention, OrganizationRetentionUpdate, RetentionPolicy, RetentionRule } from '@shared/models';

import {
    buildRetentionItems,
    buildRetentionUpdate,
    describeRetentionLowerings,
    findRetentionLowerings,
    RetentionChoice,
    RetentionLowering,
    toRetentionChoice,
} from './retention-options.util';

const POLICY: RetentionPolicy = {
    sessions: { default_days: 30, max_days: null, min_days: null, allowed: [30, 90, 180, 365, 0] },
    conversations: { default_days: 90, max_days: 180, min_days: null, allowed: [30, 90, 180] },
    audit: { default_days: 0, max_days: null, min_days: null, allowed: [30, 90, 180, 365, 0] },
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
            'Sessions older than 30 days will be removed in the next nightly cleanup. This cannot be undone.',
        ],
        [
            'names both lowered types, in the days format the select uses',
            [
                { type: 'sessions', newEffectiveDays: 30 },
                { type: 'conversations', newEffectiveDays: 365 },
            ],
            'Sessions older than 30 days and conversations older than 1 year will be removed in the next nightly cleanup. This cannot be undone.',
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

    it('does not send a stored value equal to the default that is left on the default option', () => {
        expect(
            buildRetentionUpdate(retention({ sessions_days: 30, sessions_effective_days: 30 }), {
                sessions_days: 'default',
                conversations_days: 'default',
                audit_days: 'default',
            })
        ).toBeNull();
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
    it('lists the allowed values in policy order, tagging the default once instead of adding a row for it', () => {
        expect(buildRetentionItems(retention(), 'sessions')).toEqual([
            { name: '30 days', tip: 'Default', value: 'default' },
            { name: '90 days', value: 90 },
            { name: '180 days', value: 180 },
            { name: '1 year', value: 365 },
            { name: 'Unlimited', value: 0 },
        ]);
    });

    it('tags an unlimited default on the Unlimited option', () => {
        const items = buildRetentionItems(retention(), 'audit');

        expect(items.filter((item) => item.name === 'Unlimited')).toEqual([
            { name: 'Unlimited', tip: 'Default', value: 'default' },
        ]);
    });

    it('puts a default that is not an allowed value first', () => {
        const policy: RetentionPolicy = {
            ...POLICY,
            sessions: { default_days: 60, max_days: null, min_days: null, allowed: [30, 90] },
        };

        expect(buildRetentionItems(retention({ retention_policy: policy }), 'sessions')).toEqual([
            { name: '60 days', tip: 'Default', value: 'default' },
            { name: '30 days', value: 30 },
            { name: '90 days', value: 90 },
        ]);
    });

    it.each<[string, RetentionRule, Partial<OrganizationRetention>, string, number]>([
        [
            'a stored value above the cap',
            { default_days: 90, max_days: 180, min_days: null, allowed: [30, 90, 180] },
            { conversations_days: 365, conversations_effective_days: 180 },
            '1 year (above limit, 180 days applied)',
            365,
        ],
        [
            'a stored unlimited value under a cap',
            { default_days: 90, max_days: 180, min_days: null, allowed: [30, 90, 180] },
            { conversations_days: 0, conversations_effective_days: 180 },
            'Unlimited (above limit, 180 days applied)',
            0,
        ],
        [
            'a stored value below the floor',
            { default_days: 180, max_days: null, min_days: 90, allowed: [90, 180, 365, 0] },
            { conversations_days: 30, conversations_effective_days: 90 },
            '30 days (below minimum, 90 days applied)',
            30,
        ],
    ])('keeps %s as the last option, with the days applied', (_case, rule, stored, name, value) => {
        const items = buildRetentionItems(
            retention({ ...stored, retention_policy: { ...POLICY, conversations: rule } }),
            'conversations'
        );

        expect(items.at(-1)).toEqual({ name, value });
    });
});

describe('toRetentionChoice', () => {
    it.each<[string, number | null, RetentionChoice]>([
        ['shows null as the default', null, 'default'],
        ['shows a stored value equal to the default on the default option', 30, 'default'],
        ['keeps any other stored value', 90, 90],
    ])('%s', (_case, days, expected) => {
        expect(toRetentionChoice(days, 30)).toBe(expected);
    });
});
