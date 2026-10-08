import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DragHoverDirective } from './drag-hover.directive';

@Component({
    imports: [DragHoverDirective],
    template: `
        <div
            class="host"
            appDragHover
            #hover="appDragHover"
            [dragHoverDelay]="300"
            [dragHoverDisabled]="disabled()"
            [class.hovering]="hover.isHovering()"
            (dragHover)="hovers = hovers + 1"
        >
            <span class="child">child</span>
        </div>
    `,
})
class HostComponent {
    readonly disabled = signal<boolean>(false);
    hovers = 0;
}

describe('DragHoverDirective', () => {
    let fixture: ComponentFixture<HostComponent>;

    function host(): HTMLElement {
        return (fixture.nativeElement as HTMLElement).querySelector('.host') as HTMLElement;
    }

    function dispatch(type: string, relatedTarget: EventTarget | null = null): void {
        host().dispatchEvent(Object.assign(new Event(type, { bubbles: true }), { relatedTarget }));
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.useFakeTimers();
        fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
    });

    afterEach(() => vi.useRealTimers());

    it('emits once after the drag rests on the host for the delay, and reports hovering meanwhile', () => {
        dispatch('dragenter');
        dispatch('dragover');
        expect(host().classList).toContain('hovering');

        vi.advanceTimersByTime(299);
        expect(fixture.componentInstance.hovers).toBe(0);
        vi.advanceTimersByTime(1);
        fixture.detectChanges();

        expect(fixture.componentInstance.hovers).toBe(1);
        expect(host().classList).not.toContain('hovering');
    });

    it('cancels when the drag leaves the host, but not when it moves onto a child', () => {
        dispatch('dragenter');
        dispatch('dragleave', host().querySelector('.child'));
        expect(host().classList).toContain('hovering');

        dispatch('dragleave', document.body);
        vi.advanceTimersByTime(300);

        expect(fixture.componentInstance.hovers).toBe(0);
        expect(host().classList).not.toContain('hovering');
    });

    it('cancels on drop', () => {
        dispatch('dragenter');
        dispatch('drop');
        vi.advanceTimersByTime(300);

        expect(fixture.componentInstance.hovers).toBe(0);
    });

    it('ignores drags while disabled', () => {
        fixture.componentInstance.disabled.set(true);
        fixture.detectChanges();

        dispatch('dragenter');
        vi.advanceTimersByTime(300);

        expect(fixture.componentInstance.hovers).toBe(0);
        expect(host().classList).not.toContain('hovering');
    });

    it('cancels a pending emit when it becomes disabled mid-hover (e.g. the drag ended)', () => {
        dispatch('dragenter');

        fixture.componentInstance.disabled.set(true);
        fixture.detectChanges();
        vi.advanceTimersByTime(300);
        fixture.detectChanges();

        expect(fixture.componentInstance.hovers).toBe(0);
        expect(host().classList).not.toContain('hovering');
    });
});
