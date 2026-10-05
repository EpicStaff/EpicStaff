import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { CdtTreeBlock } from '../cdt-decision-tree.model';
import { CdtDecisionTreeDetailComponent } from './cdt-decision-tree-detail.component';

function block(id: string, title = id): CdtTreeBlock {
    return {
        id,
        kind: 'row-decision',
        title,
        subtitle: null,
        // Prose, so the code block never reaches for Monaco.
        detail: { heading: 'Expression', language: 'text', body: 'a > 1' },
        clickable: true,
        target: null,
        warning: null,
        note: null,
        chip: null,
        searchText: title.toLowerCase(),
    };
}

/**
 * jsdom does no layout, so `scrollTop` would read 0 whatever was written. A plain
 * writable property stands in for it; the test is about when the component resets
 * it, not about how the window lays out.
 */
function stubScrollTop(element: HTMLElement, value: number): void {
    Object.defineProperty(element, 'scrollTop', { value, writable: true, configurable: true });
}

/**
 * jsdom has no `ResizeObserver`. Without one the component's geometry setup
 * throws into Angular's error handler, which logs and carries on, so the tests
 * below would pass while never reaching the wiring they are about.
 */
class FakeResizeObserver {
    public static instances: FakeResizeObserver[] = [];
    public readonly observed: { target: Element; options?: ResizeObserverOptions }[] = [];
    public disconnected = false;

    constructor(public readonly callback: ResizeObserverCallback) {
        FakeResizeObserver.instances.push(this);
    }

    public observe(target: Element, options?: ResizeObserverOptions): void {
        this.observed.push({ target, options });
    }

    /** What the browser does when an observed box changes size. */
    public trigger(): void {
        this.callback([], this as unknown as ResizeObserver);
    }

    public unobserve(): void {}

    public disconnect(): void {
        this.disconnected = true;
    }
}

beforeEach(() => {
    FakeResizeObserver.instances = [];
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
});

afterEach(() => vi.unstubAllGlobals());

describe('CdtDecisionTreeDetailComponent scroll reset', () => {
    let fixture: ComponentFixture<CdtDecisionTreeDetailComponent>;
    let body: HTMLElement;

    beforeEach(async () => {
        fixture = TestBed.createComponent(CdtDecisionTreeDetailComponent);
        fixture.componentRef.setInput('block', block('row-0:decision'));
        fixture.componentRef.setInput('explainOffered', true);
        fixture.detectChanges();
        await fixture.whenStable();

        body = (fixture.nativeElement as HTMLElement).querySelector('.cdt-tree-detail__body') as HTMLElement;
        stubScrollTop(body, 250);
    });

    it('scrolls the window back to the top when another block is shown', async () => {
        fixture.componentRef.setInput('block', block('row-1:decision'));
        fixture.detectChanges();
        await fixture.whenStable();

        expect(body.scrollTop).toBe(0);
    });

    it('keeps the position when the same block arrives as a new object', async () => {
        fixture.componentRef.setInput('block', block('row-0:decision', 'Renamed rule'));
        fixture.detectChanges();
        await fixture.whenStable();

        expect(body.scrollTop).toBe(250);
    });

    it('keeps the position when only the explanation changes', async () => {
        fixture.componentRef.setInput('explanation', { status: 'loading' });
        fixture.detectChanges();
        await fixture.whenStable();

        expect(body.scrollTop).toBe(250);
    });
});

/** Pins one layout number on an element; jsdom computes none of them. */
function stubNumber(element: Element, property: string, value: number): void {
    Object.defineProperty(element, property, { value, writable: true, configurable: true });
}

function stubTop(element: Element, top: number): void {
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({ top } as DOMRect);
}

describe('CdtDecisionTreeDetailComponent code block geometry', () => {
    let fixture: ComponentFixture<CdtDecisionTreeDetailComponent>;
    let body: HTMLElement;

    beforeEach(async () => {
        // Frames run at once, so a `scroll` event is measured before the assertion.
        // Returns 0, the component's "no frame pending": a real frame id is never 0
        // and a real callback never runs inside `requestAnimationFrame`.
        vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
            callback(0);
            return 0;
        });
        vi.stubGlobal('cancelAnimationFrame', () => undefined);

        fixture = TestBed.createComponent(CdtDecisionTreeDetailComponent);
        fixture.componentRef.setInput('block', block('row-0:decision'));
        fixture.componentRef.setInput('explainOffered', true);
        fixture.detectChanges();
        await fixture.whenStable();

        body = (fixture.nativeElement as HTMLElement).querySelector('.cdt-tree-detail__body') as HTMLElement;
    });

    // jsdom lays nothing out, so every size is 0: the block gets no height and a
    // window with nothing to scroll counts as at its end. What matters here is that
    // the first render writes both, not the numbers.
    it('writes the block height and the at-end class on the first render', () => {
        expect(body.style.getPropertyValue('--cdt-code-block-height')).toBe('0px');
        expect(body.classList).toContain('cdt-tree-detail__body--at-end');
    });

    it("watches the window, the explanation and the code block's host for size changes", () => {
        const element = fixture.nativeElement as HTMLElement;

        expect(FakeResizeObserver.instances).toHaveLength(1);
        expect(FakeResizeObserver.instances[0].observed).toEqual([
            { target: body, options: undefined },
            { target: element.querySelector('.cdt-tree-detail__section'), options: undefined },
            { target: element.querySelector('app-cdt-decision-tree-code'), options: { box: 'border-box' } },
        ]);
    });

    describe('with a laid-out window', () => {
        let code: HTMLElement;

        // A 600px window at y=100 that can scroll 300px, a code block starting at
        // y=180 and the section's 24px bottom padding as the gap below the block.
        beforeEach(() => {
            const element = fixture.nativeElement as HTMLElement;
            code = element.querySelector('.cdt-tree-code') as HTMLElement;
            (element.querySelector('.cdt-tree-detail__section--data') as HTMLElement).style.paddingBottom = '24px';

            stubTop(body, 100);
            stubNumber(body, 'clientHeight', 600);
            stubNumber(body, 'scrollHeight', 900);
            stubNumber(body, 'scrollTop', 300);
            stubTop(code, 180);
        });

        it('sizes the block to stop the gap above the window bottom, and lets it scroll at the end', () => {
            body.dispatchEvent(new Event('scroll'));

            // 100 + 600 - 24 - 180
            expect(body.style.getPropertyValue('--cdt-code-block-height')).toBe('496px');
            expect(body.classList).toContain('cdt-tree-detail__body--at-end');
        });

        it('sends the code back to line 1 and stops it scrolling when the window leaves the end', () => {
            body.dispatchEvent(new Event('scroll'));
            stubNumber(code, 'scrollTop', 120);

            stubNumber(body, 'scrollTop', 100);
            body.dispatchEvent(new Event('scroll'));

            expect(code.scrollTop).toBe(0);
            expect(body.classList).not.toContain('cdt-tree-detail__body--at-end');
        });

        it('remeasures when an observed box resizes', () => {
            // The code section reopening: the host's top padding pushes the block down.
            stubTop(code, 196);

            FakeResizeObserver.instances[0].trigger();

            // 100 + 600 - 24 - 196
            expect(body.style.getPropertyValue('--cdt-code-block-height')).toBe('480px');
        });
    });

    it('lets go of the listener and the observer when destroyed', () => {
        const removeEventListener = vi.spyOn(body, 'removeEventListener');

        fixture.destroy();

        expect(removeEventListener).toHaveBeenCalledWith('scroll', expect.any(Function));
        expect(FakeResizeObserver.instances[0].disconnected).toBe(true);
    });
});

describe('CdtDecisionTreeDetailComponent explain control', () => {
    function render(explainOffered: boolean): HTMLElement {
        const fixture = TestBed.createComponent(CdtDecisionTreeDetailComponent);
        fixture.componentRef.setInput('block', block('row-0:decision'));
        fixture.componentRef.setInput('explainOffered', explainOffered);
        fixture.componentRef.setInput('explanation', {
            status: 'ready',
            text: 'Stored text',
            generatedBy: 'model',
            fingerprint: 'fingerprint',
        });
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it('shows Explain when the editor may change the flow', () => {
        expect(render(true).querySelector('.cdt-tree-detail__explain-group')).not.toBeNull();
    });

    it('hides Explain in a read-only editor but still shows the stored explanation', () => {
        const element = render(false);

        expect(element.querySelector('.cdt-tree-detail__explain-group')).toBeNull();
        expect(element.querySelector('.cdt-tree-detail__explanation')?.textContent).toContain('Stored text');
    });
});
