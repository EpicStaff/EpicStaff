import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { createEnvironmentInjector, DestroyRef, EnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { GetMeResponse, ShortcutParams, ShortcutSettings } from '@shared/models';

import { ProfileService } from '../../services/auth/profile.service';
import { ConfigService } from '../../services/config';
import { ToastMessage, ToastService } from '../../services/notifications';
import { chordFromEvent } from '../core/keymap/key-chord.util';
import { KeymapService, PLATFORM_IS_MAC } from './keymap.service';

const PROFILE_URL = '/api/profile/';

const BASE_USER: GetMeResponse = {
    id: 7,
    email: 'jane@example.com',
    display_name: 'Jane Doe',
    is_superadmin: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    memberships: [],
    active_organization_id: 3,
    active_permissions: null,
    avatar_url: null,
    completed_tours: ['quick-start'],
    custom_shortcuts: { custom: [], overrides: {} },
};

describe('KeymapService', () => {
    let httpMock: HttpTestingController;
    let profile: ProfileService;
    let toasts: ToastMessage[];
    const attached: HTMLElement[] = [];

    function setUp(isMac = false): void {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: PLATFORM_IS_MAC, useValue: isMac },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        profile = TestBed.inject(ProfileService);
        toasts = [];
        TestBed.inject(ToastService).toasts$.subscribe((current) => (toasts = current));
    }

    function keymap(): KeymapService {
        return TestBed.inject(KeymapService);
    }

    type CustomRow = readonly [string, string | null];

    function shortcutSettings(...custom: readonly CustomRow[]): ShortcutSettings {
        return { custom: custom.map(([action, keys]) => ({ action, keys })), overrides: {} };
    }

    function loadUser(...custom: readonly CustomRow[]): void {
        profile.getCurrentUser().subscribe();
        httpMock
            .expectOne({ method: 'GET', url: PROFILE_URL })
            .flush({ ...BASE_USER, custom_shortcuts: shortcutSettings(...custom) });
    }

    function nextPatch(): { body: unknown; succeed: () => void; fail: () => void } {
        const request = httpMock.expectOne({ method: 'PATCH', url: PROFILE_URL });
        const body = request.request.body as { custom_shortcuts: ShortcutSettings };
        return {
            body,
            succeed: () => request.flush({ ...BASE_USER, custom_shortcuts: body.custom_shortcuts }),
            fail: () => request.flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' }),
        };
    }

    function attach<T extends HTMLElement>(element: T): T {
        document.body.appendChild(element);
        attached.push(element);
        return element;
    }

    function press(init: KeyboardEventInit): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
        window.dispatchEvent(event);
        return event;
    }

    function pressOn(target: HTMLElement, init: KeyboardEventInit): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
        target.dispatchEvent(event);
        return event;
    }

    function buttonInside(containerTag: string, containerClass?: string): HTMLButtonElement {
        const container = attach(document.createElement(containerTag));
        if (containerClass) container.classList.add(containerClass);
        const button = document.createElement('button');
        container.appendChild(button);
        return button;
    }

    afterEach(() => {
        attached.splice(0).forEach((element) => element.remove());
        window.getSelection()?.removeAllRanges();
        try {
            httpMock.verify();
        } finally {
            TestBed.resetTestingModule();
        }
    });

    describe('dispatch', () => {
        beforeEach(() => setUp());

        it('calls the handler of the action bound to the pressed chord and blocks the browser default', () => {
            const handler = vi.fn();
            keymap().register('editing.undo', handler);

            const event = press({ code: 'KeyZ', key: 'я', ctrlKey: true });

            expect(handler).toHaveBeenCalledOnce();
            expect(event.defaultPrevented).toBe(true);
        });

        it('leaves the browser default alone when no handler is registered for the chord', () => {
            keymap().register('editing.undo', vi.fn());

            const event = press({ code: 'KeyS', ctrlKey: true });

            expect(event.defaultPrevented).toBe(false);
        });

        it.each([
            ['US', { key: '/', code: 'Slash', ctrlKey: true }],
            ['German, where / is Shift+7', { key: '/', code: 'Digit7', ctrlKey: true, shiftKey: true }],
            ['French, where / is Shift+colon', { key: '/', code: 'Period', ctrlKey: true, shiftKey: true }],
        ])('opens the shortcuts list on Ctrl+/ on a %s layout', (_layout, init) => {
            const openShortcuts = vi.fn();
            keymap().register('navigating.shortcuts', openShortcuts);

            press(init);

            expect(openShortcuts).toHaveBeenCalledOnce();
        });

        it('routes each redo chord to redo', () => {
            const redo = vi.fn();
            const undo = vi.fn();
            keymap().register('editing.redo', redo);
            keymap().register('editing.undo', undo);

            press({ code: 'KeyZ', ctrlKey: true, shiftKey: true });
            press({ code: 'KeyY', ctrlKey: true });

            expect(redo).toHaveBeenCalledTimes(2);
            expect(undo).not.toHaveBeenCalled();
        });

        it('calls every registered handler for one action (panel save and flow save both fire)', () => {
            const first = vi.fn();
            const second = vi.fn();
            keymap().register('editing.save', first, { allowInEditable: false });
            keymap().register('editing.save', second);

            press({ code: 'KeyS', ctrlKey: true });

            expect(first).toHaveBeenCalledOnce();
            expect(second).toHaveBeenCalledOnce();
        });

        it('stops calling a handler after unregister and keeps the others', () => {
            const removed = vi.fn();
            const kept = vi.fn();
            const unregister = keymap().register('editing.paste', removed);
            keymap().register('editing.paste', kept);

            unregister();
            press({ code: 'KeyV', ctrlKey: true });

            expect(removed).not.toHaveBeenCalled();
            expect(kept).toHaveBeenCalledOnce();
        });

        it('ignores events from editable targets and, for node actions, from the side panel', () => {
            const handler = vi.fn();
            keymap().register('node.agent', handler);

            pressOn(attach(document.createElement('input')), { code: 'KeyA', shiftKey: true });
            pressOn(buttonInside('app-node-panel-shell'), { code: 'KeyA', shiftKey: true });
            pressOn(buttonInside('div', 'monaco-editor'), { code: 'KeyA', shiftKey: true });

            expect(handler).not.toHaveBeenCalled();
        });

        it('delivers non-node actions from the side panel', () => {
            const handler = vi.fn();
            keymap().register('editing.save', handler);

            pressOn(buttonInside('app-node-panel-shell'), { code: 'KeyS', ctrlKey: true });

            expect(handler).toHaveBeenCalledOnce();
        });

        it('delivers from an input only to handlers that allow editable targets', () => {
            const panelEscape = vi.fn();
            const canvasEscape = vi.fn();
            keymap().register('editing.escape', panelEscape, { allowInEditable: true });
            keymap().register('editing.escape', canvasEscape);

            pressOn(attach(document.createElement('textarea')), { code: 'Escape' });

            expect(panelEscape).toHaveBeenCalledOnce();
            expect(canvasEscape).not.toHaveBeenCalled();
        });

        it('lets the browser copy selected text instead of copying nodes', () => {
            const copy = vi.fn();
            keymap().register('editing.copy', copy);
            const paragraph = attach(document.createElement('p'));
            paragraph.textContent = 'selected text';
            window.getSelection()?.selectAllChildren(paragraph);

            const event = press({ code: 'KeyC', ctrlKey: true });

            expect(copy).not.toHaveBeenCalled();
            expect(event.defaultPrevented).toBe(false);
        });

        it('copies nodes when no text is selected', () => {
            const copy = vi.fn();
            keymap().register('editing.copy', copy);

            press({ code: 'KeyC', ctrlKey: true });

            expect(copy).toHaveBeenCalledOnce();
        });

        it('adds one node per press, not one per auto-repeat while the key is held', () => {
            const handler = vi.fn();
            keymap().register('node.agent', handler);

            press({ code: 'KeyA', shiftKey: true });
            press({ code: 'KeyA', shiftKey: true, repeat: true });

            expect(handler).toHaveBeenCalledOnce();
        });

        it('removes a handler when the destroyRef passed with it is destroyed', () => {
            const componentInjector = createEnvironmentInjector([], TestBed.inject(EnvironmentInjector));
            const destroyed = vi.fn();
            const alive = vi.fn();
            keymap().register('editing.undo', destroyed, { destroyRef: componentInjector.get(DestroyRef) });
            keymap().register('editing.undo', alive);

            componentInjector.destroy();
            press({ code: 'KeyZ', ctrlKey: true });

            expect(destroyed).not.toHaveBeenCalled();
            expect(alive).toHaveBeenCalledOnce();
        });

        it('stops listening once the injector is destroyed', () => {
            const handler = vi.fn();
            keymap().register('editing.undo', handler);

            TestBed.resetTestingModule();
            press({ code: 'KeyZ', ctrlKey: true });

            expect(handler).not.toHaveBeenCalled();
        });
    });

    describe('dispatch with custom shortcuts', () => {
        beforeEach(() => setUp());

        it('fires an action on its custom key and keeps its base key working', () => {
            loadUser(['editing.save', 'Alt+KeyS']);
            const save = vi.fn();
            keymap().register('editing.save', save);

            press({ code: 'KeyS', altKey: true });
            press({ code: 'KeyS', ctrlKey: true });

            expect(save).toHaveBeenCalledTimes(2);
        });

        it('sends a node key a custom row took to that row action, not to the node', () => {
            loadUser(['node.task', 'Shift+KeyP']);
            const python = vi.fn();
            const task = vi.fn();
            keymap().register('node.python', python);
            keymap().register('node.task', task);

            press({ code: 'KeyP', shiftKey: true });

            expect(task).toHaveBeenCalledOnce();
            expect(python).not.toHaveBeenCalled();
        });
    });

    describe('on mac', () => {
        beforeEach(() => setUp(true));

        it('treats Cmd as Mod and a physical Ctrl as a different chord', () => {
            const undo = vi.fn();
            keymap().register('editing.undo', undo);

            press({ code: 'KeyZ', metaKey: true });
            press({ code: 'KeyZ', ctrlKey: true });

            expect(undo).toHaveBeenCalledOnce();
        });

        it('refuses a physical Ctrl chord because it could never fire on Windows or Linux', () => {
            loadUser();
            const recorded = chordFromEvent(
                new KeyboardEvent('keydown', { code: 'KeyA', ctrlKey: true, shiftKey: true }),
                true
            );

            expect(keymap().addCustom('editing.save', recorded ?? '')).toMatchObject({ rejection: 'mac-ctrl' });
            httpMock.expectNone({ method: 'PATCH' });
        });
    });

    describe('bindings', () => {
        beforeEach(() => setUp());

        it('picks up custom shortcuts loaded after the editor started', () => {
            const service = keymap();
            loadUser(['editing.save', 'Alt+KeyS'], ['node.task', null]);

            expect(service.bindings().get('editing.save')).toEqual(['Mod+KeyS', 'Alt+KeyS']);
            expect(service.customShortcuts().map((row) => [row.action, row.chord])).toEqual([
                ['editing.save', 'Alt+KeyS'],
                ['node.task', null],
            ]);
        });

        it('separates the base key from custom keys and marks a node whose key was taken', () => {
            loadUser(['node.python', 'Alt+KeyQ'], ['editing.save', 'Shift+KeyT']);

            expect(keymap().builtInBindings().get('node.python')).toEqual(['Shift+KeyP']);
            expect(keymap().bindings().get('node.python')).toEqual(['Shift+KeyP', 'Alt+KeyQ']);
            expect(keymap().builtInBindings().get('node.task')).toEqual([]);
            expect([...keymap().unboundIds()]).toEqual(['node.task']);
        });

        it('tells which action holds a chord', () => {
            loadUser(['node.task', 'Shift+KeyP']);

            expect(keymap().actionForChord('Shift+KeyP')).toBe('node.task');
            expect(keymap().actionForChord('Mod+Shift+KeyZ')).toBe('editing.redo');
            expect(keymap().actionForChord('Alt+KeyQ')).toBeNull();
        });

        it('does not crash on a stored value in an older shape', () => {
            profile.getCurrentUser().subscribe();
            httpMock
                .expectOne({ method: 'GET', url: PROFILE_URL })
                .flush({ ...BASE_USER, custom_shortcuts: { 'node.agent': 'Shift+KeyB' } });

            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyA']);
            expect(keymap().customShortcuts()).toEqual([]);
        });

        it('makes no HTTP request when the user has no custom shortcuts', () => {
            loadUser();
            keymap().bindings();
            press({ code: 'KeyA', shiftKey: true });

            httpMock.expectNone({ method: 'PATCH' });
        });
    });

    describe('custom shortcuts', () => {
        beforeEach(() => setUp());

        it('addCustom shows the new key at once and PATCHes the whole list', () => {
            loadUser(['editing.undo', 'Alt+KeyU']);

            const result = keymap().addCustom('editing.save', 'Alt+KeyS');

            expect(result).toMatchObject({ accepted: true, displaces: null });
            expect(keymap().bindings().get('editing.save')).toEqual(['Mod+KeyS', 'Alt+KeyS']);
            const patch = nextPatch();
            expect(patch.body).toEqual({
                custom_shortcuts: shortcutSettings(['editing.undo', 'Alt+KeyU'], ['editing.save', 'Alt+KeyS']),
            });
            patch.succeed();
            expect(keymap().customShortcuts().at(-1)?.id).toBe(result.accepted ? result.customShortcutId : undefined);
        });

        it('adds a row without a key', () => {
            loadUser();

            expect(keymap().addCustom('node.task', null)).toMatchObject({ accepted: true, displaces: null });

            expect(nextPatch().body).toEqual({ custom_shortcuts: shortcutSettings(['node.task', null]) });
            expect(keymap().bindings().get('node.task')).toEqual(['Shift+KeyT']);
        });

        it('says which node lost its key when a custom row takes it', () => {
            loadUser();

            expect(keymap().addCustom('node.task', 'Shift+KeyP')).toMatchObject({
                accepted: true,
                displaces: 'node.python',
            });
            nextPatch().succeed();

            expect(keymap().builtInBindings().get('node.python')).toEqual([]);
            expect(keymap().unboundIds().has('node.python')).toBe(true);
        });

        it('rejects a protected key, the action own key or a key another row has, without saving', () => {
            loadUser(['editing.undo', 'Alt+KeyU']);

            expect(keymap().addCustom('node.agent', 'Mod+KeyC')).toMatchObject({ rejection: 'reserved' });
            expect(keymap().addCustom('editing.save', 'Mod+KeyS')).toMatchObject({
                rejection: 'taken',
                takenBy: { action: 'editing.save', source: 'default' },
            });
            expect(keymap().addCustom('node.agent', 'Alt+KeyU')).toMatchObject({
                rejection: 'taken',
                takenBy: { action: 'editing.undo', source: 'custom' },
            });
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('refuses an action that cannot have custom keys', () => {
            loadUser();

            expect(() => keymap().addCustom('editing.escape', 'Alt+KeyE')).toThrow();
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('updateCustom changes the row in place, keeps its id and can clear its key', () => {
            loadUser(['editing.undo', 'Alt+KeyU'], ['editing.save', 'Alt+KeyS']);
            const [undo, save] = keymap().customShortcuts();

            expect(keymap().updateCustom(undo.id, { chord: 'Alt+KeyZ' })).toEqual({ accepted: true, displaces: null });
            const first = nextPatch();
            expect(first.body).toEqual({
                custom_shortcuts: shortcutSettings(['editing.undo', 'Alt+KeyZ'], ['editing.save', 'Alt+KeyS']),
            });
            first.succeed();

            expect(keymap().updateCustom(save.id, { action: 'editing.redo', chord: null })).toMatchObject({
                accepted: true,
            });
            expect(nextPatch().body).toEqual({
                custom_shortcuts: shortcutSettings(['editing.undo', 'Alt+KeyZ'], ['editing.redo', null]),
            });
            expect(
                keymap()
                    .customShortcuts()
                    .map((row) => row.id)
            ).toEqual([undo.id, save.id]);
        });

        it('removeCustom drops the row and gives the node its key back', () => {
            loadUser(['node.task', 'Shift+KeyP']);

            keymap().removeCustom(keymap().customShortcuts()[0].id);

            expect(keymap().bindings().get('node.python')).toEqual(['Shift+KeyP']);
            expect(nextPatch().body).toEqual({ custom_shortcuts: shortcutSettings() });
        });

        it('drops rows for actions it does not know when saving', () => {
            loadUser(['action.from-a-newer-version', 'Alt+KeyN']);

            expect(keymap().addCustom('editing.save', 'Alt+KeyN')).toMatchObject({ accepted: true });

            expect(nextPatch().body).toEqual({ custom_shortcuts: shortcutSettings(['editing.save', 'Alt+KeyN']) });
        });

        it('keeps a stored row whose key no longer works and saves it without a key', () => {
            loadUser(['node.agent', 'Mod+KeyV']);

            expect(
                keymap()
                    .customShortcuts()
                    .map((row) => [row.action, row.chord])
            ).toEqual([['node.agent', null]]);
            keymap().addCustom('editing.save', 'Alt+KeyS');

            expect(nextPatch().body).toEqual({
                custom_shortcuts: shortcutSettings(['node.agent', null], ['editing.save', 'Alt+KeyS']),
            });
        });

        it('a failed save restores the rows and tells the user', () => {
            loadUser(['editing.undo', 'Alt+KeyU']);
            const [undo] = keymap().customShortcuts();

            keymap().addCustom('editing.save', 'Alt+KeyS');
            nextPatch().fail();

            expect(keymap().customShortcuts()).toEqual([undo]);
            expect(keymap().bindings().get('editing.save')).toEqual(['Mod+KeyS']);
            expect(toasts.map((toast) => [toast.type, toast.message])).toEqual([['error', 'Could not save shortcut']]);
        });

        it('keeps the ids of untouched rows and answers "missing" for a row a failed save took back', () => {
            loadUser(['editing.undo', 'Alt+KeyU'], ['editing.save', 'Alt+KeyS']);
            const [undo, save] = keymap().customShortcuts();

            keymap().updateCustom(save.id, { chord: 'Alt+KeyD' });
            nextPatch().fail();

            const rows = keymap().customShortcuts();
            expect(rows.map((row) => [row.action, row.chord])).toEqual([
                ['editing.undo', 'Alt+KeyU'],
                ['editing.save', 'Alt+KeyS'],
            ]);
            expect(rows[0].id).toBe(undo.id);
            expect(keymap().updateCustom(save.id, { chord: 'Alt+KeyF' })).toEqual({
                accepted: false,
                rejection: 'missing',
                takenBy: null,
            });
            expect(
                keymap().checkChord('Alt+KeyF', { action: 'editing.save', customShortcutId: save.id })
            ).toMatchObject({ rejection: 'missing' });
            keymap().removeCustom(save.id);
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('does not report a failure when a later save carries the same edit', () => {
            loadUser();

            keymap().addCustom('editing.save', 'Alt+KeyS');
            keymap().addCustom('editing.undo', 'Alt+KeyU');
            nextPatch().fail();
            const second = nextPatch();
            expect(second.body).toEqual({
                custom_shortcuts: shortcutSettings(['editing.save', 'Alt+KeyS'], ['editing.undo', 'Alt+KeyU']),
            });
            second.succeed();

            expect(keymap().customShortcuts()).toHaveLength(2);
            expect(toasts).toEqual([]);
        });

        it('reports a failure once when the last queued save fails too', () => {
            loadUser();

            keymap().addCustom('editing.save', 'Alt+KeyS');
            keymap().addCustom('editing.undo', 'Alt+KeyU');
            nextPatch().fail();
            nextPatch().fail();

            expect(keymap().customShortcuts()).toEqual([]);
            expect(toasts.map((toast) => toast.message)).toEqual(['Could not save shortcut']);
        });

        it('keeps saving after a failed save', () => {
            loadUser();

            keymap().addCustom('editing.save', 'Alt+KeyS');
            nextPatch().fail();
            keymap().addCustom('editing.undo', 'Alt+KeyU');

            expect(nextPatch().body).toEqual({ custom_shortcuts: shortcutSettings(['editing.undo', 'Alt+KeyU']) });
        });

        it('a profile reload that lands while a save is pending does not undo the edit', () => {
            loadUser();

            keymap().addCustom('editing.save', 'Alt+KeyS');
            const patch = nextPatch();
            loadUser();
            expect(keymap().bindings().get('editing.save')).toEqual(['Mod+KeyS', 'Alt+KeyS']);

            patch.succeed();
            expect(keymap().bindings().get('editing.save')).toEqual(['Mod+KeyS', 'Alt+KeyS']);
        });

        it('takes a profile reload when nothing is pending', () => {
            loadUser();
            keymap().bindings();

            loadUser(['editing.save', 'Alt+KeyS']);

            expect(keymap().bindings().get('editing.save')).toEqual(['Mod+KeyS', 'Alt+KeyS']);
        });
    });

    describe('reset to defaults', () => {
        beforeEach(() => setUp());

        it('clears the keys of rows on node base keys in one PATCH and keeps unique keys', () => {
            loadUser(['node.task', 'Shift+KeyP'], ['editing.save', 'Alt+KeyS'], ['editing.undo', 'Shift+KeyA']);
            expect(keymap().defaultsResetClearCount()).toBe(2);

            keymap().resetToDefaults();

            expect(keymap().bindings().get('node.python')).toEqual(['Shift+KeyP']);
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyA']);
            expect([...keymap().unboundIds()]).toEqual([]);
            expect(keymap().defaultsResetClearCount()).toBe(0);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: shortcutSettings(
                    ['node.task', null],
                    ['editing.save', 'Alt+KeyS'],
                    ['editing.undo', null]
                ),
            });
        });

        it('does nothing when there is nothing to reset', () => {
            loadUser(['editing.save', 'Alt+KeyS']);

            keymap().resetToDefaults();

            httpMock.expectNone({ method: 'PATCH' });
        });

        it('rolls a failed reset back', () => {
            loadUser(['node.task', 'Shift+KeyP']);

            keymap().resetToDefaults();
            nextPatch().fail();

            expect(keymap().bindings().get('node.task')).toEqual(['Shift+KeyT', 'Shift+KeyP']);
            expect(keymap().unboundIds().has('node.python')).toBe(true);
        });
    });

    describe('checkChord', () => {
        beforeEach(() => setUp());

        it('previews a change without saving it', () => {
            loadUser(['editing.undo', 'Alt+KeyU']);

            expect(keymap().checkChord('Shift+KeyP', { action: 'node.task' })).toEqual({
                accepted: true,
                displaces: 'node.python',
            });
            expect(keymap().checkChord('Alt+KeyU', { action: 'node.agent' })).toMatchObject({ rejection: 'taken' });
            expect(keymap().checkChord('Backspace', { action: 'editing.save' })).toMatchObject({
                rejection: 'reserved',
            });

            expect(keymap().bindings().get('node.python')).toEqual(['Shift+KeyP']);
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('does not count the edited row as holding its own key', () => {
            loadUser(['editing.undo', 'Alt+KeyU']);
            const [undo] = keymap().customShortcuts();

            expect(keymap().checkChord('Alt+KeyU', { action: 'editing.redo', customShortcutId: undo.id })).toEqual({
                accepted: true,
                displaces: null,
            });
        });
    });

    describe('shortcuts that take a flow', () => {
        beforeEach(() => setUp());

        function loadEntries(custom: ShortcutSettings['custom']): void {
            profile.getCurrentUser().subscribe();
            httpMock
                .expectOne({ method: 'GET', url: PROFILE_URL })
                .flush({ ...BASE_USER, custom_shortcuts: { custom } });
        }

        it('hands each Subgraph key the flow of its own row', () => {
            loadEntries([
                { action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } },
                { action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 34 } },
            ]);
            const received: (ShortcutParams | null)[] = [];
            keymap().register('node.subgraph', (_event, match) => received.push(match.params));

            press({ code: 'Digit2', key: '2', altKey: true });
            press({ code: 'Digit1', key: '1', altKey: true });

            expect(received).toEqual([{ flowId: 34 }, { flowId: 12 }]);
        });

        it('hands no params to an action bound by its built-in key', () => {
            const received: (ShortcutParams | null)[] = [];
            keymap().register('node.agent', (_event, match) => received.push(match.params));

            press({ code: 'KeyA', key: 'A', shiftKey: true });

            expect(received).toEqual([null]);
        });

        it('does not fire a stored Subgraph row whose flow is missing', () => {
            loadEntries([{ action: 'node.subgraph', keys: 'Alt+Digit1' }]);
            const subgraph = vi.fn();
            keymap().register('node.subgraph', subgraph);

            const event = press({ code: 'Digit1', key: '1', altKey: true });

            expect(subgraph).not.toHaveBeenCalled();
            expect(event.defaultPrevented).toBe(false);
        });

        it('saves the flow of an added Subgraph row and keeps it when only the key is edited', () => {
            loadEntries([{ action: 'editing.save', keys: 'Alt+KeyS' }]);

            const added = keymap().addCustom('node.subgraph', 'Alt+Digit1', { flowId: 12 });
            const first = nextPatch();
            expect(first.body).toEqual({
                custom_shortcuts: {
                    overrides: {},
                    custom: [
                        { action: 'editing.save', keys: 'Alt+KeyS' },
                        { action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } },
                    ],
                },
            });
            first.succeed();

            keymap().updateCustom(added.accepted ? added.customShortcutId : '', { chord: 'Alt+Digit2' });

            expect(nextPatch().body).toEqual({
                custom_shortcuts: {
                    overrides: {},
                    custom: [
                        { action: 'editing.save', keys: 'Alt+KeyS' },
                        { action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 12 } },
                    ],
                },
            });
        });

        it('refuses a Subgraph row without a flow and saves nothing', () => {
            loadEntries([]);

            expect(keymap().addCustom('node.subgraph', 'Alt+Digit1')).toMatchObject({
                accepted: false,
                rejection: 'params',
            });
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('keeps row ids when the saved flow comes back with its keys in another order', () => {
            loadEntries([{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12, tab: 'a' } }]);
            const [before] = keymap().customShortcuts();

            loadEntries([{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { tab: 'a', flowId: 12 } }]);

            expect(keymap().customShortcuts()[0].id).toBe(before.id);
        });
    });

    describe('node key overrides', () => {
        beforeEach(() => setUp());

        function loadSettings(settings: unknown): void {
            profile.getCurrentUser().subscribe();
            httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush({ ...BASE_USER, custom_shortcuts: settings });
        }

        it('gives a node a new key, PATCHes the override next to the Additional rows and fires on it', () => {
            loadSettings({ custom: [{ action: 'editing.save', keys: 'Alt+KeyS' }] });
            const python = vi.fn();
            keymap().register('node.python', python);

            expect(keymap().setNodeKey('node.python', 'Alt+KeyQ')).toEqual({ accepted: true, displaces: null });

            expect(nextPatch().body).toEqual({
                custom_shortcuts: {
                    custom: [{ action: 'editing.save', keys: 'Alt+KeyS' }],
                    overrides: { 'node.python': 'Alt+KeyQ' },
                },
            });
            press({ code: 'KeyQ', key: 'q', altKey: true });
            press({ code: 'KeyP', key: 'P', shiftKey: true });
            expect(python).toHaveBeenCalledOnce();
            expect(keymap().overriddenIds().has('node.python')).toBe(true);
        });

        it('resets one node key with a PATCH that drops only its override', () => {
            loadSettings({ custom: [], overrides: { 'node.python': 'Alt+KeyQ', 'node.task': null } });

            expect(keymap().resetNodeKey('node.python')).toEqual({ accepted: true, displaces: null });

            expect(nextPatch().body).toEqual({ custom_shortcuts: { custom: [], overrides: { 'node.task': null } } });
            expect(keymap().builtInBindings().get('node.python')).toEqual(['Shift+KeyP']);
        });

        it('refuses to reset a node key whose default an Additional row holds, without saving', () => {
            loadSettings({
                custom: [{ action: 'node.agent', keys: 'Shift+KeyP' }],
                overrides: { 'node.python': 'Alt+KeyQ' },
            });

            expect(keymap().resetNodeKey('node.python')).toMatchObject({
                accepted: false,
                rejection: 'taken',
                takenBy: { action: 'node.agent', source: 'custom' },
            });
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('clears every override on reset to defaults', () => {
            loadSettings({ custom: [], overrides: { 'node.python': 'Alt+KeyQ' } });
            expect(keymap().canResetToDefaults()).toBe(true);

            keymap().resetToDefaults();

            expect(nextPatch().body).toEqual({ custom_shortcuts: { custom: [], overrides: {} } });
            expect(keymap().canResetToDefaults()).toBe(false);
        });

        it('does not save when a node key is set to the key it already has', () => {
            loadSettings({ custom: [], overrides: { 'node.python': 'Alt+KeyQ' } });

            keymap().setNodeKey('node.python', 'Alt+KeyQ');

            httpMock.expectNone({ method: 'PATCH' });
        });
    });

    describe('canvas panning keys', () => {
        beforeEach(() => setUp());

        it('leaves the key alone when the registration does not want this event', () => {
            const pan = vi.fn();
            keymap().register('navigating.pan-right', pan, { when: () => false });

            const event = press({ code: 'ArrowRight', key: 'ArrowRight' });

            expect(pan).not.toHaveBeenCalled();
            expect(event.defaultPrevented).toBe(false);
        });

        it.each([
            ['an arrow', { code: 'ArrowRight', key: 'ArrowRight' }, 'navigating.pan-right'],
            ['Ctrl and an arrow', { code: 'ArrowLeft', key: 'ArrowLeft', ctrlKey: true }, 'navigating.pan-left-fast'],
        ] as const)('fires the pan action for %s, also while the key is held', (_case, init, action) => {
            const pan = vi.fn();
            keymap().register(action, pan, { runOutsideAngular: true });

            press(init);
            press({ ...init, repeat: true });

            expect(pan).toHaveBeenCalledTimes(2);
        });

        it('does not pan from inside the side panel', () => {
            const pan = vi.fn();
            keymap().register('navigating.pan-right', pan);

            pressOn(buttonInside('app-node-panel-shell'), { code: 'ArrowRight', key: 'ArrowRight' });

            expect(pan).not.toHaveBeenCalled();
        });
    });
});
