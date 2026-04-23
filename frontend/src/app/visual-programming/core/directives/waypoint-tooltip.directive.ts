import { DOCUMENT } from '@angular/common';
import { Directive, HostListener, Inject, OnDestroy, Renderer2 } from '@angular/core';

@Directive({
    selector: '[appWaypointTooltip]',
    standalone: true,
})
export class WaypointTooltipDirective implements OnDestroy {
    private tooltipEl: HTMLElement | null = null;

    constructor(
        private renderer: Renderer2,
        @Inject(DOCUMENT) private document: Document
    ) {}

    @HostListener('mouseover', ['$event'])
    onMouseOver(event: MouseEvent): void {
        const target = event.target as Element;
        let text: string | null = null;

        if (target.classList.contains('f-candidate')) {
            text = 'Move';
        } else if (target.classList.contains('f-waypoint')) {
            text = 'LMB: straighten';
        }

        if (text) {
            this.show(text, event.clientX, event.clientY);
        } else {
            this.hide();
        }
    }

    @HostListener('mousemove', ['$event'])
    onMouseMove(event: MouseEvent): void {
        if (this.tooltipEl && this.tooltipEl.style.display !== 'none') {
            this.position(event.clientX, event.clientY);
        }
    }

    @HostListener('mouseleave')
    onMouseLeave(): void {
        this.hide();
    }

    private show(text: string, x: number, y: number): void {
        if (!this.tooltipEl) {
            const el: HTMLElement = this.renderer.createElement('div');
            this.renderer.addClass(el, 'waypoint-tooltip');
            this.renderer.appendChild(this.document.body, el);
            this.tooltipEl = el;
        }
        const el = this.tooltipEl;
        el.textContent = text;
        this.position(x, y);
        this.renderer.setStyle(el, 'display', 'block');
    }

    private position(x: number, y: number): void {
        if (!this.tooltipEl) return;
        this.renderer.setStyle(this.tooltipEl, 'left', `${x + 14}px`);
        this.renderer.setStyle(this.tooltipEl, 'top', `${y - 36}px`);
    }

    private hide(): void {
        if (this.tooltipEl) {
            this.renderer.setStyle(this.tooltipEl, 'display', 'none');
        }
    }

    ngOnDestroy(): void {
        if (this.tooltipEl) {
            this.renderer.removeChild(this.document.body, this.tooltipEl);
            this.tooltipEl = null;
        }
    }
}
