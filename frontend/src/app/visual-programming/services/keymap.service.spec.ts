import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { createEnvironmentInjector, DestroyRef, EnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { GetMeResponse } from '@shared/models';

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
    shortcut_overrides: {},
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

    function loadUser(overrides: Record<string, string>): void {
        profile.getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush({ ...BASE_USER, shortcut_overrides: overrides });
    }

    function nextPatch(): { body: unknown; succeed: () => void; fail: () => void } {
        const request = httpMock.expectOne({ method: 'PATCH', url: PROFILE_URL });
        const body = request.request.body as { shortcut_overrides: Record<string, string> };
        return {
            body,
            succeed: () => request.flush({ ...BASE_USER, shortcut_overrides: body.shortcut_overrides }),
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

        it('uses a rebound chord and frees the default', () => {
            loadUser({ 'node.agent': 'Shift+KeyB' });
            const handler = vi.fn();
            keymap().register('node.agent', handler);

            press({ code: 'KeyA', shiftKey: true });
            press({ code: 'KeyB', shiftKey: true });

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
            loadUser({});
            const recorded = chordFromEvent(
                new KeyboardEvent('keydown', { code: 'KeyA', ctrlKey: true, shiftKey: true }),
                true
            );

            expect(keymap().setOverride('node.agent', recorded ?? '')).toBe('mac-ctrl');
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('ignores a stored physical Ctrl override', () => {
            loadUser({ 'node.agent': 'Ctrl+Shift+KeyA' });

            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyA']);
            expect(keymap().overriddenIds().has('node.agent')).toBe(false);
        });
    });

    describe('bindings', () => {
        beforeEach(() => setUp());

        it('lists the defaults when the user has no overrides', () => {
            loadUser({});

            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyA']);
            expect(keymap().bindings().get('editing.redo')).toEqual(['Mod+Shift+KeyZ', 'Mod+KeyY']);
        });

        it('applies a valid override and drops the default for that action', () => {
            loadUser({ 'node.agent': 'Alt+KeyG' });

            expect(keymap().bindings().get('node.agent')).toEqual(['Alt+KeyG']);
        });

        it('picks up overrides loaded after the editor started', () => {
            const service = keymap();
            loadUser({ 'node.agent': 'Alt+KeyG' });

            expect(service.bindings().get('node.agent')).toEqual(['Alt+KeyG']);
        });

        it('ignores a stored physical Ctrl override outside mac too', () => {
            loadUser({ 'node.agent': 'Ctrl+Shift+KeyA' });

            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyA']);
        });

        it('lists only actions whose chord comes from a valid stored override', () => {
            loadUser({ 'node.agent': 'Shift+KeyB', 'node.task': 'Mod+KeyS', 'node.note': 'Shift+KeyP' });

            expect([...keymap().overriddenIds()]).toEqual(['node.agent']);
        });

        it('tells which action holds a chord', () => {
            loadUser({ 'node.agent': 'Shift+KeyB' });

            expect(keymap().actionForChord('Shift+KeyB')).toBe('node.agent');
            expect(keymap().actionForChord('Mod+Shift+KeyZ')).toBe('editing.redo');
            expect(keymap().actionForChord('Shift+KeyA')).toBeNull();
        });

        it('ignores invalid overrides: unknown id, not rebindable, malformed, reserved, bare, clashing', () => {
            loadUser({
                'gone.action': 'Shift+KeyQ',
                'editing.undo': 'Shift+KeyQ',
                'node.agent': 'Mod+KeyS',
                'node.task': 'Shift+KeyP',
                'node.note': 'Shift+Hyper+KeyN',
                'node.key-value': 'KeyV',
            });

            const bindings = keymap().bindings();
            expect(bindings.has('gone.action' as never)).toBe(false);
            expect(bindings.get('editing.undo')).toEqual(['Mod+KeyZ']);
            expect(bindings.get('node.agent')).toEqual(['Shift+KeyA']);
            expect(bindings.get('node.task')).toEqual(['Shift+KeyT']);
            expect(bindings.get('node.python')).toEqual(['Shift+KeyP']);
            expect(bindings.get('node.note')).toEqual(['Shift+KeyN']);
            expect(bindings.get('node.key-value')).toEqual(['Shift+KeyV']);
        });

        it('lets an action take a default that its owner gave up, whatever the key order', () => {
            loadUser({ 'node.agent': 'Shift+KeyP', 'node.python': 'Shift+KeyB' });

            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyP']);
            expect(keymap().bindings().get('node.python')).toEqual(['Shift+KeyB']);
        });

        it('gives a clashing chord to the action listed first', () => {
            loadUser({ 'node.agent': 'Shift+KeyB', 'node.python': 'Shift+KeyB' });

            expect(keymap().bindings().get('node.python')).toEqual(['Shift+KeyB']);
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyA']);
        });

        it('makes no HTTP request when the user has no overrides', () => {
            loadUser({});
            keymap().bindings();
            press({ code: 'KeyA', shiftKey: true });

            httpMock.expectNone({ method: 'PATCH' });
        });
    });

    describe('editing overrides', () => {
        beforeEach(() => setUp());

        it('setOverride rejects without saving and saves on success', () => {
            loadUser({});

            expect(keymap().setOverride('node.agent', 'Shift+KeyT')).toBe('taken');
            expect(keymap().setOverride('node.agent', 'Mod+KeyS')).toBe('reserved');
            expect(keymap().setOverride('node.agent', 'KeyB')).toBe('bare-key');
            expect(keymap().setOverride('node.agent', 'Tab')).toBe('bare-key');
            expect(keymap().actionForChord('Shift+KeyT')).toBe('node.task');
            httpMock.expectNone({ method: 'PATCH' });

            expect(keymap().setOverride('node.agent', 'Shift+KeyB')).toBeNull();
            const patch = nextPatch();
            expect(patch.body).toEqual({ shortcut_overrides: { 'node.agent': 'Shift+KeyB' } });
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyB']);

            patch.succeed();
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyB']);
        });

        it('refuses to rebind an action that is not rebindable', () => {
            loadUser({});

            expect(() => keymap().setOverride('editing.undo', 'Shift+KeyB')).toThrow();
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('does not save when the chord is already the action binding', () => {
            loadUser({ 'node.agent': 'Shift+KeyB' });

            expect(keymap().setOverride('node.agent', 'Shift+KeyB')).toBeNull();
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('a failed save restores the previous binding and tells the user', () => {
            loadUser({ 'node.agent': 'Alt+KeyG' });

            keymap().setOverride('node.agent', 'Shift+KeyB');
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyB']);
            nextPatch().fail();

            expect(keymap().bindings().get('node.agent')).toEqual(['Alt+KeyG']);
            expect(toasts.map((toast) => [toast.type, toast.message])).toEqual([['error', 'Could not save shortcut']]);
        });

        it('does not report a failure when a later save carries the same edit', () => {
            loadUser({});

            keymap().setOverride('node.agent', 'Shift+KeyB');
            keymap().setOverride('node.task', 'Shift+KeyJ');
            nextPatch().fail();
            const second = nextPatch();
            expect(second.body).toEqual({
                shortcut_overrides: { 'node.agent': 'Shift+KeyB', 'node.task': 'Shift+KeyJ' },
            });
            second.succeed();

            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyB']);
            expect(keymap().bindings().get('node.task')).toEqual(['Shift+KeyJ']);
            expect(toasts).toEqual([]);
        });

        it('reports a failure once when the last queued save fails too', () => {
            loadUser({});

            keymap().setOverride('node.agent', 'Shift+KeyB');
            keymap().setOverride('node.task', 'Shift+KeyJ');
            nextPatch().fail();
            nextPatch().fail();

            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyA']);
            expect(toasts.map((toast) => toast.message)).toEqual(['Could not save shortcut']);
        });

        it('marks an action as overridden as soon as it is edited and clears it on reset', () => {
            loadUser({});

            keymap().setOverride('node.agent', 'Shift+KeyB');
            expect(keymap().overriddenIds().has('node.agent')).toBe(true);
            nextPatch().succeed();

            keymap().resetOverride('node.agent');
            expect(keymap().overriddenIds().has('node.agent')).toBe(false);
            nextPatch().succeed();
        });

        it('keeps saving after a failed save', () => {
            loadUser({});

            keymap().setOverride('node.agent', 'Shift+KeyB');
            nextPatch().fail();
            keymap().setOverride('node.task', 'Shift+KeyJ');

            expect(nextPatch().body).toEqual({ shortcut_overrides: { 'node.task': 'Shift+KeyJ' } });
        });

        it('two quick edits send two PATCHes in order and keep both', () => {
            loadUser({});

            keymap().setOverride('node.agent', 'Shift+KeyB');
            keymap().setOverride('node.task', 'Shift+KeyJ');

            const first = nextPatch();
            expect(first.body).toEqual({ shortcut_overrides: { 'node.agent': 'Shift+KeyB' } });
            first.succeed();
            expect(keymap().bindings().get('node.task')).toEqual(['Shift+KeyJ']);

            const second = nextPatch();
            expect(second.body).toEqual({
                shortcut_overrides: { 'node.agent': 'Shift+KeyB', 'node.task': 'Shift+KeyJ' },
            });
            second.succeed();
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyB']);
            expect(keymap().bindings().get('node.task')).toEqual(['Shift+KeyJ']);
        });

        it('a profile reload that lands while a save is pending does not undo the edit', () => {
            loadUser({});

            keymap().setOverride('node.agent', 'Shift+KeyB');
            const patch = nextPatch();
            loadUser({});
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyB']);

            patch.succeed();
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyB']);
        });

        it('resetOverride removes the key from the saved map', () => {
            loadUser({ 'node.agent': 'Shift+KeyB', 'node.task': 'Shift+KeyJ' });

            expect(keymap().resetOverride('node.agent')).toBeNull();

            const patch = nextPatch();
            expect(patch.body).toEqual({ shortcut_overrides: { 'node.task': 'Shift+KeyJ' } });
            patch.succeed();
            expect(keymap().bindings().get('node.agent')).toEqual(['Shift+KeyA']);
        });

        it('resetOverride refuses when another action now uses the default', () => {
            loadUser({ 'node.python': 'Shift+KeyB', 'node.agent': 'Shift+KeyP' });

            expect(keymap().resetOverride('node.python')).toBe('taken');
            httpMock.expectNone({ method: 'PATCH' });
        });

        it('setting an override back to its default removes the key instead of storing it', () => {
            loadUser({ 'node.agent': 'Shift+KeyB' });

            keymap().setOverride('node.agent', 'Shift+KeyA');

            expect(nextPatch().body).toEqual({ shortcut_overrides: {} });
        });

        it('keeps overrides it does not know when saving', () => {
            loadUser({ 'node.from-a-newer-version': 'Shift+KeyQ' });

            keymap().setOverride('node.agent', 'Shift+KeyB');

            expect(nextPatch().body).toEqual({
                shortcut_overrides: { 'node.from-a-newer-version': 'Shift+KeyQ', 'node.agent': 'Shift+KeyB' },
            });
        });
    });
});
