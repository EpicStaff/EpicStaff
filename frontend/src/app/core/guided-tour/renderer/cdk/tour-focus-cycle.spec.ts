import { TestBed } from '@angular/core/testing';

import { TourFocusCycle } from './tour-focus-cycle';

const PAGE_HTML = `
    <button id="page-button">Elsewhere on the page</button>
    <div id="target">
        <input id="target-input" />
        <button id="target-button">Activate</button>
    </div>
    <div id="popover">
        <div id="card" tabindex="-1">
            <button id="back">Back</button>
            <button id="next">Next</button>
        </div>
    </div>
    <div id="dialog"><button id="dialog-button">Don't save</button></div>
`;

describe('TourFocusCycle', () => {
    let cycle: TourFocusCycle;
    let escapeCount: number;
    let page: HTMLElement;

    beforeEach(() => {
        // jsdom lays nothing out; CDK's InteractivityChecker skips elements without a box.
        vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue({ length: 1 } as DOMRectList);
        page = document.createElement('div');
        page.innerHTML = PAGE_HTML;
        document.body.appendChild(page);
        escapeCount = 0;
        cycle = TestBed.runInInjectionContext(() => new TourFocusCycle(() => escapeCount++));
        cycle.attach(byId('popover'));
        cycle.setTarget(byId('target'));
    });

    afterEach(() => {
        cycle.dispose();
        page.remove();
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    function byId(id: string): HTMLElement {
        const element = document.getElementById(id);
        if (!element) {
            throw new Error(`No #${id}`);
        }
        return element;
    }

    /** Dispatches a keydown on the focused element, as the browser does, and returns it. */
    function press(key: string, options: KeyboardEventInit = {}): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...options });
        (document.activeElement ?? document.body).dispatchEvent(event);
        return event;
    }

    it.each([
        ['the popover’s last button', 'next', false, 'target-input'],
        ['the target’s last control', 'target-button', false, 'back'],
        ['the popover’s first button, backwards', 'back', true, 'target-button'],
        ['the target’s first control, backwards', 'target-input', true, 'next'],
        ['a popover button to the next one', 'back', false, 'next'],
        ['the card focused at step start', 'card', false, 'back'],
        ['the card focused at step start, backwards', 'card', true, 'target-button'],
    ])('moves Tab from %s', (_case, fromId, shiftKey, expectedId) => {
        byId(fromId).focus();

        const event = press('Tab', { shiftKey });

        expect(event.defaultPrevented).toBe(true);
        expect(document.activeElement?.id).toBe(expectedId);
    });

    it('cycles within the popover when the step has no target', () => {
        cycle.setTarget(null);
        byId('next').focus();

        press('Tab');

        expect(document.activeElement?.id).toBe('back');
    });

    it('leaves Tab to the browser outside the popover and the target, e.g. in a dialog opened mid-step', () => {
        byId('dialog-button').focus();

        const event = press('Tab');

        expect(event.defaultPrevented).toBe(false);
        expect(document.activeElement?.id).toBe('dialog-button');
    });

    it.each([
        ['the popover', 'next', 1],
        ['the target', 'target-input', 1],
        ['a dialog opened mid-step', 'dialog-button', 0],
        ['the page outside the step', 'page-button', 0],
    ])('asks to close on Escape from %s only when the focus is in the step', (_case, fromId, expectedEscapes) => {
        byId(fromId).focus();

        press('Escape');

        expect(escapeCount).toBe(expectedEscapes);
    });

    it('leaves Escape to the target when its own handler took it (e.g. closing its dropdown)', () => {
        byId('target-input').addEventListener('keydown', (event) => event.preventDefault());
        byId('target-input').focus();

        press('Escape');

        expect(escapeCount).toBe(0);
    });

    it('keeps Escape in the popover from reaching overlays beneath the tour', () => {
        let reachedBody = false;
        const onBodyKeydown = (): void => {
            reachedBody = true;
        };
        document.body.addEventListener('keydown', onBodyKeydown);
        byId('next').focus();

        press('Escape');

        document.body.removeEventListener('keydown', onBodyKeydown);
        expect(escapeCount).toBe(1);
        expect(reachedBody).toBe(false);
    });

    describe('presenting a step', () => {
        const card = { focusCard: (): void => byId('card').focus() };

        function announcedText(): string {
            vi.advanceTimersByTime(200);
            return document.querySelector('.cdk-live-announcer-element')?.textContent ?? '';
        }

        beforeEach(() => vi.useFakeTimers());

        it('moves the focus into the popover when the tour starts, without an announcement', () => {
            byId('page-button').focus();

            cycle.presentStep(card, 'Step 1 of 3: Open Settings', true);

            expect(document.activeElement?.id).toBe('card');
            expect(announcedText()).toBe('');
        });

        it('keeps the focus in the popover when the user moved on with its buttons', () => {
            byId('next').focus();

            cycle.presentStep(card, 'Step 2 of 3: Quickstart', false);

            expect(document.activeElement?.id).toBe('card');
            expect(announcedText()).toBe('');
        });

        it('leaves the focus on the page and announces the step when the user moved on from the page', () => {
            byId('target-button').focus();

            cycle.presentStep(card, 'Step 3 of 3: Pick a provider', false);

            expect(document.activeElement?.id).toBe('target-button');
            expect(announcedText()).toBe('Step 3 of 3: Pick a provider');
        });
    });
});
