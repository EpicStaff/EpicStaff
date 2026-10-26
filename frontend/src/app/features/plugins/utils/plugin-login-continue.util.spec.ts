import { DefaultUrlSerializer } from '@angular/router';

import { continueWithOrganization, parsePluginLoginContinue } from './plugin-login-continue.util';

const STATE = 'S'.repeat(43);
const CHALLENGE = 'C'.repeat(43);
const QUERY = `plugin=weather&state=${STATE}&code_challenge=${CHALLENGE}&code_challenge_method=S256`;
const CONTINUE = `/api/auth/plugin-authorize/?${QUERY}`;

describe('parsePluginLoginContinue', () => {
    it('accepts the authorize request EpicStaff rebuilt, with or without org', () => {
        expect(parsePluginLoginContinue(CONTINUE)).toEqual({ path: CONTINUE, plugin: 'weather', state: STATE });
        expect(parsePluginLoginContinue(`${CONTINUE}&org=3`)).toEqual({
            path: `${CONTINUE}&org=3`,
            plugin: 'weather',
            state: STATE,
        });
    });

    it('reads continue as the router decodes the form-encoded redirect EpicStaff answers with', () => {
        const redirect = `/plugin-login?${new URLSearchParams({ continue: `${CONTINUE}&org=3` }).toString()}`;
        const decoded = new DefaultUrlSerializer().parse(redirect).queryParamMap.get('continue');

        expect(decoded).toBe(`${CONTINUE}&org=3`);
        expect(parsePluginLoginContinue(decoded)).toEqual({
            path: `${CONTINUE}&org=3`,
            plugin: 'weather',
            state: STATE,
        });
    });

    it.each([
        ['missing', null],
        ['empty', ''],
        ['protocol-relative', `//evil.example${CONTINUE}`],
        ['absolute', `https://evil.example${CONTINUE}`],
        ['absolute on the own host', `http://epicstaff.localhost${CONTINUE}`],
        ['dot segments', `/api/auth/plugin-authorize/../../../evil?${QUERY}`],
        ['another path', `/api/auth/refresh/?${QUERY}`],
        ['no trailing slash', `/api/auth/plugin-authorize?${QUERY}`],
        ['a path in the query', `${CONTINUE}&next=/evil`],
        ['a backslash', `${CONTINUE}&next=\\evil`],
        ['a fragment', `${CONTINUE}#x`],
        ['encoded twice', encodeURIComponent(CONTINUE)],
        ['no query', '/api/auth/plugin-authorize/?'],
        ['too long', `${CONTINUE}&x=${'a'.repeat(4000)}`],
        ['prompt', `${CONTINUE}&prompt=none`],
        ['prompt with an empty value', `${CONTINUE}&prompt`],
        ['prompt, percent-encoded', `${CONTINUE}&pr%6Fmpt=none`],
        ['prompt, encoded with upper-case escapes', `${CONTINUE}&%70%72%6F%6D%70%74=none`],
        ['no plugin', `/api/auth/plugin-authorize/?state=${STATE}`],
        ['no state', '/api/auth/plugin-authorize/?plugin=weather&code_challenge_method=S256'],
        ['an empty state', '/api/auth/plugin-authorize/?plugin=weather&state='],
        ['two states', `${CONTINUE}&state=other`],
        ['two plugins', `${CONTINUE}&plugin=atlas`],
        ['a plugin id that breaks the manifest rule', CONTINUE.replace('weather', 'Weather')],
        ['a plugin id with an encoded dot', CONTINUE.replace('weather', 'weather%2E')],
    ])('refuses %s', (_name, value) => {
        expect(parsePluginLoginContinue(value)).toBeNull();
    });
});

describe('continueWithOrganization', () => {
    it('adds org after the other parameters', () => {
        const target = parsePluginLoginContinue(CONTINUE);

        expect(target && continueWithOrganization(target, 7)).toBe(`${CONTINUE}&org=7`);
    });

    it('replaces an org the request already had, in place', () => {
        const target = parsePluginLoginContinue(`/api/auth/plugin-authorize/?plugin=weather&org=3&state=${STATE}`);

        expect(target && continueWithOrganization(target, 9)).toBe(
            `/api/auth/plugin-authorize/?plugin=weather&org=9&state=${STATE}`
        );
    });

    it('keeps a result that is itself a valid continue', () => {
        const target = parsePluginLoginContinue(`${CONTINUE}&org=3&org=4`);
        const next = target && continueWithOrganization(target, 5);

        expect(next).toBe(`${CONTINUE}&org=5`);
        expect(parsePluginLoginContinue(next)).not.toBeNull();
    });
});
