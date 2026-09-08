import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    output,
    signal,
    ViewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ImportResult } from '../../../../../../core/models/import-result.model';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { getEntityTypeLabel, getIconColorForEntityType } from '../../utils/entity-icon.util';
import { getEntityTypeCount } from '../../utils/entity-result.util';
import { EntityIconComponent } from '../entity-icon/entity-icon.component';

@Component({
    selector: 'app-import-summary-tabs',
    imports: [AppSvgIconComponent, MatTooltipModule, EntityIconComponent],
    templateUrl: './import-summary-tabs.component.html',
    styleUrls: ['./import-summary-tabs.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ImportSummaryTabsComponent implements AfterViewInit {
    private readonly destroyRef = inject(DestroyRef);

    public readonly importResult = input.required<ImportResult>();
    public readonly entityTypes = input.required<string[]>();
    public readonly isSingleGroup = input<boolean>(false);
    public readonly totalCount = input<number>(0);

    public readonly tabClick = output<string>();

    @ViewChild('summaryList') summaryListRef!: ElementRef<HTMLElement>;

    private readonly SCROLL_STEP = 240;
    private readonly _scrollLeft = signal(0);
    private readonly _scrollWidth = signal(0);
    private readonly _clientWidth = signal(0);

    public readonly canScrollLeft = computed(() => this._scrollLeft() > 0);
    public readonly canScrollRight = computed(() => this._scrollLeft() < this._scrollWidth() - this._clientWidth() - 1);

    protected readonly getEntityTypeLabel = getEntityTypeLabel;
    protected readonly getIconColorForEntityType = getIconColorForEntityType;

    public getEntityTypeCount(entityType: string): number {
        return getEntityTypeCount(this.importResult(), entityType);
    }

    public ngAfterViewInit(): void {
        this.onSummaryScroll();

        const el = this.summaryListRef?.nativeElement;
        if (!el) return;

        const observer = new ResizeObserver(() => {
            this.onSummaryScroll();
        });
        observer.observe(el);

        this.destroyRef.onDestroy(() => observer.disconnect());
    }

    public onSummaryScroll(): void {
        const el = this.summaryListRef?.nativeElement;
        if (!el) return;
        this._scrollLeft.set(el.scrollLeft);
        this._scrollWidth.set(el.scrollWidth);
        this._clientWidth.set(el.clientWidth);
    }

    public scrollSummary(direction: -1 | 1): void {
        const el = this.summaryListRef?.nativeElement;
        if (!el) return;
        el.scrollBy({ left: direction * this.SCROLL_STEP, behavior: 'smooth' });
    }
}
