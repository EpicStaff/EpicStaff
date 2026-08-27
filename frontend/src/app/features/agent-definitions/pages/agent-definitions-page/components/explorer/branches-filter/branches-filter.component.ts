import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    inject,
    input,
    NgZone,
    OnDestroy,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';

import { EXPLORER_SECTIONS, ExplorerSectionDef, ExplorerSectionId } from '../../../../../models/explorer.model';

@Component({
    selector: 'app-branches-filter',
    imports: [AppSvgIconComponent, ButtonComponent],
    templateUrl: './branches-filter.component.html',
    styleUrls: ['./branches-filter.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BranchesFilterComponent implements AfterViewInit, OnDestroy {
    private readonly ngZone = inject(NgZone);

    selected = input.required<Set<ExplorerSectionId>>();

    save = output<Set<ExplorerSectionId>>();
    cancel = output<void>();

    readonly sections: ExplorerSectionDef[] = EXPLORER_SECTIONS;

    readonly draft = signal<Set<ExplorerSectionId> | null>(null);

    private readonly footerRef = viewChild<ElementRef<HTMLElement>>('footer');
    readonly footerStage = signal<0 | 1 | 2>(0);
    private resizeObserver: ResizeObserver | null = null;

    ngAfterViewInit(): void {
        const footer = this.footerRef()?.nativeElement;
        if (!footer || typeof ResizeObserver === 'undefined') return;

        this.ngZone.runOutsideAngular(() => {
            this.resizeObserver = new ResizeObserver(() => this.evaluateFooter(footer));
            this.resizeObserver.observe(footer);
            setTimeout(() => this.evaluateFooter(footer), 0);
        });
    }

    ngOnDestroy(): void {
        this.resizeObserver?.disconnect();
        this.resizeObserver = null;
    }

    private evaluateFooter(footer: HTMLElement): void {
        const hideClear = 'filter__footer--hide-clear';
        const collapseSave = 'filter__footer--collapse-save';

        const fits = (): boolean => footer.scrollWidth - footer.clientWidth <= 1;

        footer.classList.remove(hideClear, collapseSave);
        let stage: 0 | 1 | 2 = 0;

        if (!fits()) {
            footer.classList.add(hideClear);
            stage = 1;
            if (!fits()) {
                footer.classList.add(collapseSave);
                stage = 2;
            }
        }

        if (this.footerStage() !== stage) {
            this.ngZone.run(() => this.footerStage.set(stage));
        }
    }

    private currentDraft(): Set<ExplorerSectionId> {
        return this.draft() ?? new Set(this.selected());
    }

    isChecked(id: ExplorerSectionId): boolean {
        return this.currentDraft().has(id);
    }

    toggle(section: ExplorerSectionDef): void {
        if (section.locked) return;
        const next = new Set(this.currentDraft());
        if (next.has(section.id)) next.delete(section.id);
        else next.add(section.id);
        this.draft.set(next);
    }

    get canClear(): boolean {
        const draft = this.currentDraft();
        return this.sections.some((s) => !s.locked && draft.has(s.id));
    }

    onClearFilter(): void {
        const next = new Set<ExplorerSectionId>();
        for (const section of this.sections) {
            if (section.locked) next.add(section.id);
        }
        this.draft.set(next);
    }

    onCancel(): void {
        this.cancel.emit();
    }

    onSave(): void {
        this.save.emit(this.currentDraft());
    }
}
