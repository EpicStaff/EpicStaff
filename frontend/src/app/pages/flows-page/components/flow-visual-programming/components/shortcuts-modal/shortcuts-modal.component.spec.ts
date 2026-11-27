import { NgZone } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { GetGraphLightRequest } from '../../../../../../features/flows/models/graph.model';
import {
    createShortcutsFixture,
    ResizeObserverStub,
} from '../../../../../../visual-programming/components/shortcuts-editor/testing/shortcuts-editor.fixture';
import { KeymapService } from '../../../../../../visual-programming/services/keymap.service';
import { ShortcutsModalComponent } from './shortcuts-modal.component';

/** The popover around the shortcuts editor; the list and its editing are covered by the editor's own spec. */
describe('ShortcutsModalComponent', () => {
    const {
        fixture,
        setUp,
        tearDown,
        create,
        loadUser,
        render,
        nextPatch,
        text,
        root,
        customRows,
        buttonNamed,
        click,
        editor,
        actionPicker,
        keysBox,
        press,
        startAdding,
    } = createShortcutsFixture(ShortcutsModalComponent);

    let closedCount: number;

    function openModal(inputs: Record<string, unknown> = {}): void {
        const created = create({ open: true, pos: { top: 10, left: 10 }, ...inputs });
        closedCount = 0;
        created.componentInstance.closed.subscribe(() => (closedCount += 1));
        render();
    }

    afterEach(() => tearDown());

    it('shows the heading it is given', () => {
        setUp();
        openModal();
        fixture().componentRef.setInput('heading', 'Command & Shortcuts');
        render();

        expect(text(root().querySelector('.shortcuts__header-title')!)).toBe('Command & Shortcuts');
    });

    it('keeps the same height when minimized', () => {
        setUp();
        openModal();
        const modal = (): HTMLElement => root().querySelector('.shortcuts__modal')!;
        const height = (): string => modal().style.getPropertyValue('--shortcuts-modal-height');
        const wideHeight = height();

        click(root().querySelector('.shortcuts__size-btn')!);

        expect(modal().classList).toContain('shortcuts__modal--compact');
        expect(wideHeight).toBe('666px');
        expect(height()).toBe('666px');
    });

    it('passes the flows and the flow being edited to the editor', () => {
        const flows: GetGraphLightRequest[] = [
            { id: 1, uuid: 'uuid-1', name: 'Onboarding', description: '' },
            { id: 12, uuid: 'uuid-12', name: 'Billing', description: '' },
        ];
        setUp();
        loadUser([
            { action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 1 } },
            { action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 12 } },
        ]);
        openModal({ flows, currentFlowId: 1 });

        expect(customRows()).toEqual([
            { label: 'Subgraph: Onboarding (this flow)', keys: 'Alt 1' },
            { label: 'Subgraph: Billing', keys: 'Alt 2' },
        ]);
    });

    describe('keys pressed in the popover', () => {
        it('do not reach the canvas', () => {
            setUp();
            const undo = vi.fn();
            const deleteNodes = vi.fn();
            const keymap = TestBed.inject(KeymapService);
            keymap.register('editing.undo', undo);
            keymap.register('editing.delete', deleteNodes);
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();
            click(buttonNamed('Delete Agent Node shortcut'));
            nextPatch().succeed();
            const focused = document.activeElement as HTMLElement;

            press(focused, { key: 'z', code: 'KeyZ', ctrlKey: true });
            press(focused, { key: 'Delete', code: 'Delete' });

            expect(focused).toBe(buttonNamed('Add shortcut'));
            expect(undo).not.toHaveBeenCalled();
            expect(deleteNodes).not.toHaveBeenCalled();
            expect(closedCount).toBe(0);
        });

        it('Esc closes the popover', () => {
            setUp();
            openModal();

            press(buttonNamed('Add shortcut'), { key: 'Escape', code: 'Escape' });

            expect(closedCount).toBe(1);
        });

        it('still lets the keyboard shortcuts key toggle the popover', () => {
            setUp();
            const toggleShortcuts = vi.fn();
            TestBed.inject(KeymapService).register('navigating.shortcuts', toggleShortcuts);
            openModal();

            press(buttonNamed('Add shortcut'), { key: '/', code: 'Slash', ctrlKey: true });

            expect(toggleShortcuts).toHaveBeenCalledOnce();
        });
    });

    describe('Esc in the editor', () => {
        it('Esc cancels recording, then closes the editor, and only a further Esc closes the popover', () => {
            setUp();
            const editorEscape = vi.fn();
            TestBed.inject(KeymapService).register('editing.escape', editorEscape, { allowInEditable: true });
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();

            click(buttonNamed('Edit Agent Node shortcut'));
            click(keysBox());
            expect(text(keysBox())).toContain('Press keys');

            press(keysBox(), { key: 'Escape', code: 'Escape' });

            expect(editor()).not.toBeNull();
            expect(text(keysBox())).toContain('Alt+B');

            press(keysBox(), { key: 'Escape', code: 'Escape' });

            expect(editor()).toBeNull();
            expect(customRows()).toEqual([{ label: 'Agent Node', keys: 'Alt B' }]);
            expect(document.activeElement).toBe(buttonNamed('Edit Agent Node shortcut'));
            expect(root().querySelector('.shortcuts__modal')).not.toBeNull();
            expect(closedCount).toBe(0);
            expect(editorEscape).not.toHaveBeenCalled();

            press(document.activeElement as HTMLElement, { key: 'Escape', code: 'Escape' });

            expect(closedCount).toBe(1);
            expect(editorEscape).not.toHaveBeenCalled();
        });
    });

    describe('room for the editor', () => {
        const FLOW_WIDTH_PX = 980;
        const COLUMN_GAP_PX = 40;

        function columnPitch(): number {
            const isFourColumns = root().querySelector('.shortcuts__modal--four-columns') !== null;
            return (FLOW_WIDTH_PX + COLUMN_GAP_PX) / (isFourColumns ? 4 : 3);
        }

        function layOut(
            lastItemColumn: () => number,
            flowScrollHeight = 400,
            lastItemTop: () => number = () => 0
        ): HTMLElement {
            const content = root().querySelector<HTMLElement>('.shortcuts__content')!;
            const flow = root().querySelector<HTMLElement>('.shortcuts__flow')!;
            Object.defineProperty(content, 'clientHeight', { configurable: true, value: 560 });
            Object.defineProperty(flow, 'clientWidth', { configurable: true, value: FLOW_WIDTH_PX });
            Object.defineProperty(flow, 'scrollHeight', { configurable: true, value: flowScrollHeight });
            const realRect = Element.prototype.getBoundingClientRect;
            vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
                if (this === flow.lastElementChild) {
                    return DOMRect.fromRect({
                        x: lastItemColumn() * columnPitch(),
                        y: lastItemTop(),
                        width: 300,
                        height: 40,
                    });
                }
                return this === flow ? DOMRect.fromRect({ x: 0, y: 0, width: 980, height: 560 }) : realRect.call(this);
            });
            return content;
        }

        function columnLayout(): string {
            const modal = root().querySelector('.shortcuts__modal')!;
            const content = root().querySelector('.shortcuts__content')!;
            if (content.classList.contains('shortcuts__content--scrolling')) return 'vertical scroll';
            return modal.classList.contains('shortcuts__modal--four-columns') ? '4 columns' : '3 columns';
        }

        function refit(): void {
            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
        }

        function pass(milliseconds: number): void {
            TestBed.inject(NgZone).run(() => vi.advanceTimersByTime(milliseconds));
            render();
        }

        function preferReducedMotion(): void {
            vi.stubGlobal('matchMedia', (query: string) => ({
                matches: query === '(prefers-reduced-motion: reduce)',
                media: query,
                addListener: () => undefined,
                removeListener: () => undefined,
                addEventListener: () => undefined,
                removeEventListener: () => undefined,
            }));
        }

        function isFading(): boolean {
            return root().querySelector('.shortcuts__flow')!.classList.contains('shortcuts__flow--reflowing');
        }

        it('opens with the rows hidden and shows them only once the final layout is chosen', () => {
            setUp();
            const created = create({ open: true, pos: { top: 10, left: 10 } });
            TestBed.inject(NgZone).run(() => {
                created.detectChanges();
                TestBed.tick();
            });
            layOut(() => (columnLayout() === '3 columns' ? 5 : 2), 900);

            expect(isFading()).toBe(true);

            render();

            expect([isFading(), columnLayout()]).toEqual([false, 'vertical scroll']);
        });

        it('fades the rows out, changes the columns while they are hidden, and fades them back in after the resize', () => {
            setUp();
            openModal();
            layOut(() => 3);
            vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });

            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
            expect([isFading(), columnLayout()]).toEqual([true, '3 columns']);

            pass(120);
            expect([isFading(), columnLayout()]).toEqual([true, '4 columns']);

            pass(200);
            expect([isFading(), columnLayout()]).toEqual([false, '4 columns']);
        });

        it('does not change the columns while the panel is still widening after Expand', () => {
            setUp();
            openModal();
            let lastColumn = 2;
            layOut(() => lastColumn);
            vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
            click(root().querySelector('.shortcuts__size-btn')!);
            render();

            click(root().querySelector('.shortcuts__size-btn')!);
            render();
            lastColumn = 3;
            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
            expect([isFading(), columnLayout()]).toEqual([false, '3 columns']);

            lastColumn = 2;
            pass(200);
            expect([isFading(), columnLayout()]).toEqual([false, '3 columns']);
        });

        it('shows the rows again when Expand cuts a column change short', () => {
            setUp();
            openModal();
            layOut(() => 3);
            vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
            click(root().querySelector('.shortcuts__size-btn')!);
            render();
            pass(120);

            click(root().querySelector('.shortcuts__size-btn')!);
            render();
            pass(200);

            expect([isFading(), columnLayout()]).toEqual([false, '4 columns']);
        });

        it('drops a column change that was still fading when the list closed', () => {
            setUp();
            openModal();
            layOut(() => 3);
            vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
            expect(isFading()).toBe(true);

            fixture().componentRef.setInput('open', false);
            render();
            fixture().componentRef.setInput('open', true);
            render();
            pass(400);

            expect([isFading(), columnLayout()]).toEqual([false, '3 columns']);
        });

        it('changes the columns at once when the user prefers reduced motion', () => {
            preferReducedMotion();
            setUp();
            openModal();
            layOut(() => 3);

            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();

            expect([isFading(), columnLayout()]).toEqual([false, '4 columns']);
        });

        it('goes back to three columns when the rows end in the third column, even with no room to spare', () => {
            preferReducedMotion();
            setUp();
            openModal();
            let lastColumn = 3;
            layOut(
                () => lastColumn,
                400,
                () => 500
            );
            refit();

            lastColumn = 2;
            refit();

            expect(columnLayout()).toBe('3 columns');
        });

        it.each([
            ['few rows', 0, '3 columns'],
            ['rows that end in the third column', 2, '3 columns'],
            ['rows that overflow three columns', 3, '4 columns'],
            ['rows that overflow four columns', 4, 'vertical scroll'],
        ])('shows %s (last item in column %i) as %s', (_case, lastColumn, layout) => {
            preferReducedMotion();
            setUp();
            openModal();
            layOut(() => lastColumn);

            refit();

            expect(columnLayout()).toBe(layout);
        });

        it('goes back to three columns once the rows fit again', () => {
            preferReducedMotion();
            setUp();
            openModal();
            let lastColumn = 3;
            layOut(() => lastColumn);
            refit();
            expect(columnLayout()).toBe('4 columns');

            lastColumn = 1;
            refit();

            expect(columnLayout()).toBe('3 columns');
        });

        it('switches to vertical scrolling instead of a sideways column when the open editor does not fit', () => {
            preferReducedMotion();
            setUp();
            openModal();
            const content = layOut(() => (editor() === null ? 2 : 5));
            content.scrollLeft = 300;

            startAdding();
            ResizeObserverStub.resize(editor()!);
            render();

            expect(columnLayout()).toBe('vertical scroll');
            expect(content.scrollLeft).toBe(0);

            press(actionPicker(), { key: 'Escape', code: 'Escape' });
            press(actionPicker(), { key: 'Escape', code: 'Escape' });
            refit();

            expect(editor()).toBeNull();
            expect(columnLayout()).not.toBe('vertical scroll');
        });

        it('keeps scrolling vertically while the rows still do not fit four columns', () => {
            preferReducedMotion();
            setUp();
            openModal();
            layOut(() => 5, 900);
            refit();

            refit();

            expect(columnLayout()).toBe('vertical scroll');
        });
    });
});
