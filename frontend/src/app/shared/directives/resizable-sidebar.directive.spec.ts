import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SidebarCollapseOptions, SidebarWidthOptions, SidebarWidthService } from '../services/sidebar-width.service';
import { ResizableSidebarDirective } from './resizable-sidebar.directive';

const KEY = 'directive-test-sidebar';
const COLLAPSE: SidebarCollapseOptions = { collapsedWidth: 60, collapseThreshold: 120 };
const OPTIONS: SidebarWidthOptions = { minWidth: 180, maxWidth: 320, collapse: COLLAPSE };
const STORAGE_KEY = `sidebar-width:${KEY}`;

@Component({
    imports: [ResizableSidebarDirective],
    template: `
        <div
            #target
            class="target"
        ></div>
        <div
            class="handle"
            [appResizableSidebar]="key"
            [sidebarTarget]="target"
            [sidebarMinWidth]="180"
            [sidebarMaxWidth]="320"
            [sidebarCollapse]="collapse()"
            [sidebarSide]="side()"
        ></div>
    `,
})
class HostComponent {
    readonly key = KEY;
    readonly collapse = signal<SidebarCollapseOptions | null>(COLLAPSE);
    readonly side = signal<'left' | 'right'>('left');
}

describe('ResizableSidebarDirective', () => {
    let fixture: ComponentFixture<HostComponent>;
    let handle: HTMLElement;
    let target: HTMLElement;
    let startWidth: number;

    beforeEach(() => {
        localStorage.clear();
        vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
            callback(0);
            return 1;
        });

        // Like the main layout, the owner creates the width (collapsed by default) before the handle renders.
        TestBed.inject(SidebarWidthService).getWidth(KEY, { defaultWidth: 60, ...OPTIONS });
        fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
        const host = fixture.nativeElement as HTMLElement;
        handle = host.querySelector('.handle') as HTMLElement;
        target = host.querySelector('.target') as HTMLElement;

        // jsdom has no layout or pointer capture.
        startWidth = 60;
        target.getBoundingClientRect = () => ({ width: startWidth }) as DOMRect;
        handle.setPointerCapture = vi.fn();
        handle.hasPointerCapture = () => false;
        handle.releasePointerCapture = vi.fn();
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    function drag(fromX: number, toX: number): void {
        handle.dispatchEvent(new MouseEvent('pointerdown', { clientX: fromX, bubbles: true }));
        document.dispatchEvent(new MouseEvent('pointermove', { clientX: toX, bubbles: true }));
    }

    function release(): void {
        document.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }));
    }

    function currentWidth(): number {
        return TestBed.inject(SidebarWidthService).getWidth(KEY)();
    }

    it('exposes the handle as a labelled vertical separator', () => {
        expect(handle.getAttribute('role')).toBe('separator');
        expect(handle.getAttribute('aria-orientation')).toBe('vertical');
        expect(handle.getAttribute('aria-label')).toBe('Resize sidebar');
    });

    it('stays collapsed while dragged below the collapse threshold', () => {
        drag(60, 110);

        expect(currentWidth()).toBe(60);
    });

    it('expands to the minimum width once dragged past the collapse threshold', () => {
        drag(60, 130);

        expect(currentWidth()).toBe(180);
    });

    it('follows the pointer within the expanded range and persists on release', () => {
        drag(60, 270);
        expect(currentWidth()).toBe(270);

        release();

        expect(localStorage.getItem(`sidebar-width:${KEY}`)).toBe('270');
    });

    it('collapses an expanded sidebar dragged below the collapse threshold', () => {
        startWidth = 240;

        drag(240, 100);
        release();

        expect(currentWidth()).toBe(60);
        expect(localStorage.getItem(`sidebar-width:${KEY}`)).toBe('60');
    });

    it('only clamps to the minimum width when no collapse options are given', () => {
        fixture.componentInstance.collapse.set(null);
        fixture.detectChanges();

        drag(60, 90);

        expect(currentWidth()).toBe(180);
    });

    it('does not persist a cancelled drag', () => {
        drag(60, 270);
        document.dispatchEvent(new MouseEvent('pointercancel', { bubbles: true }));

        expect(localStorage.getItem(`sidebar-width:${KEY}`)).toBeNull();
    });

    describe('keyboard', () => {
        function startAt(width: number): void {
            TestBed.inject(SidebarWidthService).setWidth(KEY, width, OPTIONS);
        }

        function press(key: string, shiftKey = false): KeyboardEvent {
            const event = new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true });
            handle.dispatchEvent(event);
            return event;
        }

        it('exposes the current width and its range on the separator', () => {
            startAt(240);
            fixture.detectChanges();

            expect(handle.getAttribute('aria-valuenow')).toBe('240');
            expect(handle.getAttribute('aria-valuemin')).toBe('60');
            expect(handle.getAttribute('aria-valuemax')).toBe('320');
        });

        it('reports the minimum width as the smallest value when the sidebar cannot collapse', () => {
            fixture.componentInstance.collapse.set(null);
            fixture.detectChanges();

            expect(handle.getAttribute('aria-valuemin')).toBe('180');
        });

        it('expands a collapsed sidebar to the minimum width with ArrowRight and persists it', () => {
            const event = press('ArrowRight');

            expect(currentWidth()).toBe(180);
            expect(localStorage.getItem(STORAGE_KEY)).toBe('180');
            expect(event.defaultPrevented).toBe(true);
        });

        it.each([
            ['ArrowRight', false, 200, 216],
            ['ArrowRight', true, 200, 264],
            ['ArrowRight', true, 300, 320],
            ['ArrowLeft', false, 200, 184],
            ['ArrowLeft', true, 300, 236],
        ])('%s (shift: %s) moves %ipx to %ipx', (key, shiftKey, from, expected) => {
            startAt(from);

            press(key, shiftKey);

            expect(currentWidth()).toBe(expected);
        });

        it('stops at the minimum width before collapsing with ArrowLeft', () => {
            startAt(190);

            press('ArrowLeft', true);
            expect(currentWidth()).toBe(180);

            press('ArrowLeft');
            expect(currentWidth()).toBe(60);
            expect(localStorage.getItem(STORAGE_KEY)).toBe('60');
        });

        it('jumps to the smallest and the largest width with Home and End', () => {
            startAt(240);

            press('Home');
            expect(currentWidth()).toBe(60);

            press('End');
            expect(currentWidth()).toBe(320);
        });

        it('toggles between collapsed and the minimum width with Enter', () => {
            press('Enter');
            expect(currentWidth()).toBe(180);

            startAt(280);
            press('Enter');
            expect(currentWidth()).toBe(60);
        });

        it('ignores Enter and never collapses when the sidebar cannot collapse', () => {
            fixture.componentInstance.collapse.set(null);
            fixture.detectChanges();
            startAt(200);

            const enter = press('Enter');
            expect(enter.defaultPrevented).toBe(false);
            expect(currentWidth()).toBe(200);

            press('ArrowLeft', true);
            press('ArrowLeft', true);
            expect(currentWidth()).toBe(180);

            press('Home');
            expect(currentWidth()).toBe(180);
        });

        it('leaves other keys alone', () => {
            startAt(200);

            const event = press('a');

            expect(event.defaultPrevented).toBe(false);
            expect(currentWidth()).toBe(200);
            expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
        });
    });

    describe('right sidebar', () => {
        beforeEach(() => {
            fixture.componentInstance.side.set('right');
            fixture.componentInstance.collapse.set(null);
            fixture.detectChanges();
            startWidth = 240;
            TestBed.inject(SidebarWidthService).setWidth(KEY, startWidth, OPTIONS);
        });

        function press(key: string): void {
            handle.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
        }

        it('grows when the handle is dragged left and persists on release', () => {
            drag(500, 430);
            expect(currentWidth()).toBe(310);

            release();

            expect(localStorage.getItem(STORAGE_KEY)).toBe('310');
        });

        it('shrinks when the handle is dragged right', () => {
            drag(500, 540);

            expect(currentWidth()).toBe(200);
        });

        it.each([
            ['ArrowLeft', 256],
            ['ArrowRight', 224],
        ])('%s moves the width to %ipx', (key, expected) => {
            press(key);

            expect(currentWidth()).toBe(expected);
        });
    });
});
