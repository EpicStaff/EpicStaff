import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    OnChanges,
    OnInit,
    output,
    signal,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { debounceTime, distinctUntilChanged, Subject } from 'rxjs';

export interface ChunkSearchParams {
    idFilter: number | 'all';
    textQuery: string;
}

@Component({
    selector: 'app-chunk-search-bar',
    templateUrl: './chunk-search-bar.component.html',
    styleUrls: ['./chunk-search-bar.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [FormsModule, AppSvgIconComponent, MatTooltip],
})
export class ChunkSearchBarComponent implements OnInit, OnChanges {
    totalChunks = input.required<number>();
    totalMatches = input<number>(0);
    currentMatchIndex = input<number>(0);
    searchLoading = input<boolean>(false);
    resetKey = input<number | null>(null);

    searchChange = output<ChunkSearchParams>();
    prevMatch = output<void>();
    nextMatch = output<void>();

    dropdownOpen = signal(false);
    selectedId = signal<number | 'all'>('all');
    textQuery = signal('');
    idInputValue = signal('All');
    visibleIds = signal<number[]>([]);

    private readonly TEXT_DEBOUNCE = 300;
    private readonly LAZY_PAGE_SIZE = 50;
    private textInput$ = new Subject<string>();
    private destroyRef = inject(DestroyRef);

    @ViewChild('idInput') private idInput!: ElementRef<HTMLInputElement>;

    matchDisplay = computed(() => {
        if (!this.textQuery()) return '-';
        if (this.searchLoading()) return '...';
        return `${this.currentMatchIndex()} / ${this.totalMatches()}`;
    });

    isPrevDisabled = computed(() => this.currentMatchIndex() <= 1 || !this.textQuery());
    isNextDisabled = computed(() => this.currentMatchIndex() >= this.totalMatches() || !this.textQuery());

    ngOnInit(): void {
        this.textInput$
            .pipe(debounceTime(this.TEXT_DEBOUNCE), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
            .subscribe((value) => {
                this.textQuery.set(value);
                this.emitSearch();
            });

        this.loadVisibleIds('');
    }

    ngOnChanges(changes: SimpleChanges): void {
        this.loadVisibleIds('');

        if (changes['resetKey'] && !changes['resetKey'].firstChange) {
            this.selectedId.set('all');
            this.idInputValue.set('All');
            this.textQuery.set('');
            this.textInput$.next('');
        }
    }

    onTextInput(value: string): void {
        this.textInput$.next(value);
    }

    onIdInputFocus(): void {
        this.dropdownOpen.set(true);
        this.idInput.nativeElement.select();
    }

    onIdInputBlur(): void {
        this.dropdownOpen.set(false);
        this.idInputValue.set(this.selectedId() === 'all' ? 'All' : `ID ${this.selectedId()}`);
    }

    onIdInputChange(value: string): void {
        this.idInputValue.set(value);
        this.loadVisibleIds(value);
    }

    selectId(id: number | 'all'): void {
        this.selectedId.set(id);
        this.idInputValue.set(id === 'all' ? 'All' : `ID ${id}`);
        this.dropdownOpen.set(false);
        this.emitSearch();
    }

    onIdInputKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter') {
            const raw = this.idInputValue().replace(/\D/g, '');
            const num = Number(raw);
            if (num >= 1 && num <= this.totalChunks()) {
                this.selectId(num);
            } else if (!raw || this.idInputValue().toLowerCase() === 'all') {
                this.selectId('all');
            }
            this.idInput.nativeElement.blur();
        }
    }

    onPrev(): void {
        if (!this.isPrevDisabled()) this.prevMatch.emit();
    }

    onNext(): void {
        if (!this.isNextDisabled()) this.nextMatch.emit();
    }

    private emitSearch(): void {
        this.searchChange.emit({
            idFilter: this.selectedId(),
            textQuery: this.textQuery(),
        });
    }

    private loadVisibleIds(filter: string): void {
        const total = this.totalChunks();
        const cleanFilter = filter.replace(/\D/g, '');
        const ids: number[] = [];

        if (cleanFilter) {
            for (let i = 1; i <= total && ids.length < this.LAZY_PAGE_SIZE; i++) {
                if (String(i).includes(cleanFilter)) {
                    ids.push(i);
                }
            }
        } else {
            for (let i = 1; i <= Math.min(total, this.LAZY_PAGE_SIZE); i++) {
                ids.push(i);
            }
        }

        this.visibleIds.set(ids);
    }

    onDropdownScroll(event: Event): void {
        const el = event.target as HTMLElement;
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 50) {
            this.loadMoreIds();
        }
    }

    private loadMoreIds(): void {
        const current = this.visibleIds();
        if (!current.length) return;

        const lastId = current[current.length - 1];
        const total = this.totalChunks();
        const cleanFilter = this.idInputValue().replace(/\D/g, '');
        const moreIds: number[] = [];

        for (let i = lastId + 1; i <= total && moreIds.length < this.LAZY_PAGE_SIZE; i++) {
            if (!cleanFilter || String(i).includes(cleanFilter)) {
                moreIds.push(i);
            }
        }

        if (moreIds.length) {
            this.visibleIds.update((ids) => [...ids, ...moreIds]);
        }
    }
}
