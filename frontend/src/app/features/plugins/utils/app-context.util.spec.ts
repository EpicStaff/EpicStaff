import { activeMenuItem, EPICSTAFF_CONTEXT, menuPathSegments, navigationContextOf } from './app-context.util';

describe('navigationContextOf', () => {
    it.each([
        ['/plugins/asg', 'asg', []],
        ['/plugins/asg/projects/2', 'asg', ['projects', '2']],
        ['/plugins/asg/projects?tab=content#top', 'asg', ['projects']],
        ['/plugins/asg/a%2Fb', 'asg', ['a/b']],
    ])('reads %s as the app %s at %j', (url, identifier, pageSegments) => {
        expect(navigationContextOf(url)).toEqual({ kind: 'app', identifier, pageSegments });
    });

    it.each([
        ['an EpicStaff page', '/flows/my'],
        ['the root', '/'],
        ['/plugins alone', '/plugins'],
        ['/plugins with a query only', '/plugins?identifier=asg'],
        ['a plugin address with matrix params', '/plugins/asg;identifier=chat'],
        ['matrix params further down', '/plugins/asg/projects;tab=1'],
        ['the plugins admin page', '/workspace/plugins/asg'],
        ['a malformed escape', '/plugins/asg/%E0%A4%A'],
    ])('reads %s as EpicStaff', (_, url) => {
        expect(navigationContextOf(url)).toEqual(EPICSTAFF_CONTEXT);
    });
});

describe('menuPathSegments', () => {
    it.each([
        ['/', []],
        ['/projects', ['projects']],
        ['/a/b-c_d.e~f', ['a', 'b-c_d.e~f']],
    ])('splits %s into %j', (path, segments) => {
        expect(menuPathSegments(path)).toEqual(segments);
    });

    it.each([
        'projects',
        '',
        '/a/',
        '/a//b',
        '/a?x=1',
        '/a#b',
        '/a%20b',
        '/a/..',
        '/./a',
        `/${'a'.repeat(256)}`,
        42,
        null,
    ])('refuses %j', (path) => {
        expect(menuPathSegments(path)).toBeNull();
    });
});

describe('activeMenuItem', () => {
    const overview = { path: '/' };
    const projects = { path: '/projects' };
    const projectsArchive = { path: '/projects/archive' };
    const items = [overview, projects, projectsArchive];

    it('picks the root item on the root page only', () => {
        expect(activeMenuItem(items, [])).toBe(overview);
        expect(activeMenuItem([overview], ['reports'])).toBeNull();
    });

    it('picks the longest segment-wise prefix', () => {
        expect(activeMenuItem(items, ['projects'])).toBe(projects);
        expect(activeMenuItem(items, ['projects', '2'])).toBe(projects);
        expect(activeMenuItem(items, ['projects', 'archive', '7'])).toBe(projectsArchive);
    });

    it('does not take a longer segment for its own', () => {
        expect(activeMenuItem(items, ['projectsx'])).toBeNull();
    });

    it('does not split an encoded slash', () => {
        // `/plugins/asg/a%2Fb` is one segment, `a/b`, not the page `/a/b` below `/a`.
        expect(activeMenuItem([{ path: '/a' }], ['a/b'])).toBeNull();
    });

    it('ignores an item whose path breaks the rule', () => {
        expect(activeMenuItem([{ path: '/projects/' }], ['projects'])).toBeNull();
    });
});
