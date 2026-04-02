import { Directive, ElementRef, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { Subject, takeUntil } from 'rxjs';

import { IconService } from '../services/icon.service';

@Directive({
    selector: '[appInlineSvg]',
    standalone: true,
})
export class InlineSvgDirective implements OnChanges, OnDestroy {
    @Input() path: string = '';
    @Input() svgSize: string = '';

    private destroy$ = new Subject<void>();

    constructor(
        private el: ElementRef,
        private iconService: IconService
    ) {}

    ngOnChanges(changes: SimpleChanges) {
        if (changes['path']) {
            this.loadSvg();
        }
    }

    ngOnDestroy() {
        this.destroy$.next();
        this.destroy$.complete();
    }

    private loadSvg() {
        if (!this.path) {
            this.el.nativeElement.innerHTML = '';
            return;
        }
        this.iconService
            .getIcon(this.path)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (svg: string) => {
                    this.el.nativeElement.innerHTML = svg;
                    const svgEl = this.el.nativeElement.querySelector('svg');
                    if (svgEl && this.svgSize) {
                        svgEl.setAttribute('width', this.svgSize);
                        svgEl.setAttribute('height', this.svgSize);
                    }
                },
                error: () => {
                    this.el.nativeElement.innerHTML = '';
                },
            });
    }
}
