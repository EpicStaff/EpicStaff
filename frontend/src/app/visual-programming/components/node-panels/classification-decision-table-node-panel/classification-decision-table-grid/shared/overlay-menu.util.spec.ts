import { FlexibleConnectedPositionStrategy, Overlay, OverlayConfig } from '@angular/cdk/overlay';
import { Component, ElementRef, inject, TemplateRef, viewChild, ViewContainerRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { OverlayMenuConfig, OverlayMenuController } from './overlay-menu.util';

@Component({
    template: `
        <button
            #anchor
            class="anchor"
        >
            <span class="anchor-label">Open</span>
        </button>
        <button
            #toggle
            class="toggle"
        >
            Toggle
        </button>
        <div class="outside">Outside</div>
        <ng-template #menu>
            <div class="menu-panel">Menu</div>
        </ng-template>
    `,
})
class OverlayHostComponent {
    readonly anchor = viewChild.required<ElementRef<HTMLElement>>('anchor');
    readonly toggle = viewChild.required<ElementRef<HTMLElement>>('toggle');
    readonly menu = viewChild.required<TemplateRef<unknown>>('menu');
    readonly controller = new OverlayMenuController(inject(Overlay), inject(ViewContainerRef));

    open(config?: OverlayMenuConfig): void {
        this.controller.open(this.anchor().nativeElement, this.menu(), config);
    }
}

let fixture: ComponentFixture<OverlayHostComponent>;
let host: OverlayHostComponent;

function setUp(): void {
    fixture = TestBed.createComponent(OverlayHostComponent);
    fixture.detectChanges();
    host = fixture.componentInstance;
}

/** What CDK sees for a real click: a pointerdown, then the click itself. */
function pointerClick(target: Element): void {
    target.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
}

function hostElement(selector: string): HTMLElement {
    return (fixture.nativeElement as HTMLElement).querySelector(selector) as HTMLElement;
}

function panel(): HTMLElement | null {
    return document.querySelector('.menu-panel');
}

/** The config the controller passed to `Overlay.create` on its last open. */
function spyOnCreate(): () => OverlayConfig {
    const spy = vi.spyOn(TestBed.inject(Overlay), 'create');
    return () => spy.mock.calls.at(-1)?.[0] as OverlayConfig;
}

afterEach(() => {
    host?.controller.dispose();
    vi.restoreAllMocks();
});

describe('OverlayMenuController without a backdrop', () => {
    beforeEach(setUp);

    it('opens with no backdrop to swallow the next click', () => {
        host.open({ hasBackdrop: false });

        expect(host.controller.isOpen()).toBe(true);
        expect(panel()).not.toBeNull();
        expect(document.querySelector('.cdk-overlay-backdrop')).toBeNull();
    });

    it('closes on a click outside the panel', () => {
        host.open({ hasBackdrop: false });

        pointerClick(hostElement('.outside'));

        expect(host.controller.isOpen()).toBe(false);
        expect(panel()).toBeNull();
    });

    it('stays open on a click on the anchor or anything inside it', () => {
        host.open({ hasBackdrop: false });

        pointerClick(host.anchor().nativeElement);
        pointerClick(hostElement('.anchor-label'));

        expect(host.controller.isOpen()).toBe(true);
    });

    it('stays open on a click on an element it was told to ignore', () => {
        host.open({ hasBackdrop: false, ignoreOutsideFor: [host.toggle().nativeElement] });

        pointerClick(host.toggle().nativeElement);

        expect(host.controller.isOpen()).toBe(true);
    });

    it('still closes on a click on that element when it was not told to ignore it', () => {
        host.open({ hasBackdrop: false });

        pointerClick(host.toggle().nativeElement);

        expect(host.controller.isOpen()).toBe(false);
    });

    it('stays open on a click inside the panel', () => {
        host.open({ hasBackdrop: false });

        pointerClick(panel() as HTMLElement);

        expect(host.controller.isOpen()).toBe(true);
    });
});

describe('OverlayMenuController with the default backdrop', () => {
    beforeEach(setUp);

    it('opens behind a transparent backdrop that closes it', () => {
        host.open();
        const backdrop = document.querySelector('.cdk-overlay-backdrop') as HTMLElement;

        expect(backdrop.classList).toContain('cdk-overlay-transparent-backdrop');

        backdrop.click();

        expect(host.controller.isOpen()).toBe(false);
    });
});

describe('OverlayMenuController positioning', () => {
    beforeEach(setUp);

    function positionsOf(config: OverlayConfig) {
        return (config.positionStrategy as FlexibleConnectedPositionStrategy).positions.map((position) => [
            position.originX,
            position.overlayX,
            position.originY,
            position.overlayY,
        ]);
    }

    it('aligns the end edges by default, flipping above when needed', () => {
        const lastConfig = spyOnCreate();

        host.open();

        expect(positionsOf(lastConfig())).toEqual([
            ['end', 'end', 'bottom', 'top'],
            ['end', 'end', 'top', 'bottom'],
        ]);
    });

    it('aligns the start edges with alignX start, in both positions', () => {
        const lastConfig = spyOnCreate();

        host.open({ alignX: 'start' });

        expect(positionsOf(lastConfig())).toEqual([
            ['start', 'start', 'bottom', 'top'],
            ['start', 'start', 'top', 'bottom'],
        ]);
    });

    it('keeps the viewport margin it is given, and none by default', () => {
        const withMargin = vi.spyOn(FlexibleConnectedPositionStrategy.prototype, 'withViewportMargin');

        host.open({ viewportMargin: 16 });
        host.controller.close();
        host.open();

        expect(withMargin.mock.calls.map(([margin]) => margin)).toEqual([16, 0]);
    });
});
