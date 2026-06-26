import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    output,
    signal,
    viewChild,
} from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

export interface BreadcrumbItem {
    label: string;
    icon?: string;
}

@Component({
    selector: 'app-variables-breadcrumb',
    imports: [AppSvgIconComponent],
    templateUrl: './variables-breadcrumb.component.html',
    styleUrls: ['./variables-breadcrumb.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VariablesBreadcrumbComponent {
    private readonly destroyRef = inject(DestroyRef);

    crumbs = input<BreadcrumbItem[]>([]);
    crumbClick = output<number>();

    readonly hasOverflow = signal(false);

    private readonly track = viewChild<ElementRef<HTMLElement>>('track');
    private resizeObserver: ResizeObserver | null = null;

    constructor() {
        afterNextRender(() => {
            const el = this.track()?.nativeElement;
            if (!el) return;

            this.resizeObserver = new ResizeObserver(() => this.recomputeOverflow());
            this.resizeObserver.observe(el);
            this.recomputeOverflow();
        });

        effect(() => {
            this.crumbs();
            queueMicrotask(() => this.recomputeOverflow());
        });

        this.destroyRef.onDestroy(() => {
            this.resizeObserver?.disconnect();
            this.resizeObserver = null;
        });
    }

    scrollToStart(): void {
        const el = this.track()?.nativeElement;
        if (el) {
            el.scrollTo({ left: 0, behavior: 'smooth' });
        }
    }

    private recomputeOverflow(): void {
        const el = this.track()?.nativeElement;
        if (!el) return;
        this.hasOverflow.set(el.scrollWidth > el.clientWidth + 1);
    }
}
