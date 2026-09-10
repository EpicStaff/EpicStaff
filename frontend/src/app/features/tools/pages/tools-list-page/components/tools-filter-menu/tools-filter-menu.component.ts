import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppSvgIconComponent, ButtonComponent, CheckboxComponent } from '@shared/components';

import { EMPTY_TOOLS_FILTER, ToolsFilterState, UsageBucket } from '../../../../models/tool-filter.model';

export type ToolsFilterDraft = Pick<
    ToolsFilterState,
    'showFavoriteOnly' | 'sourceBuiltIn' | 'sourceCustom' | 'usageBuckets' | 'unusedOnly'
>;

interface FilterItem {
    readonly key: string;
    readonly label: string;
    readonly checked: () => boolean;
    readonly toggle: () => void;
}

interface FilterSection {
    readonly title: string;
    readonly items: FilterItem[];
}

@Component({
    selector: 'app-tools-filter-menu',
    imports: [AppSvgIconComponent, ButtonComponent, CheckboxComponent, FormsModule],
    templateUrl: './tools-filter-menu.component.html',
    styleUrls: ['./tools-filter-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsFilterMenuComponent {
    public readonly initial = input.required<ToolsFilterState>();
    public readonly showSource = input<boolean>(false);
    public readonly includeExcludeIsSet = input<boolean>(false);
    public readonly customFilterIsSet = input<boolean>(false);

    public readonly save = output<ToolsFilterDraft>();
    public readonly cancel = output<void>();
    public readonly clear = output<void>();
    public readonly openIncludeExclude = output<void>();
    public readonly openCustomFilter = output<void>();

    protected readonly draftFavorite = signal<boolean>(false);
    protected readonly draftSourceBuiltIn = signal<boolean>(false);
    protected readonly draftSourceCustom = signal<boolean>(false);
    protected readonly draftBuckets = signal<Set<UsageBucket>>(new Set());
    protected readonly draftUnusedOnly = signal<boolean>(false);

    protected readonly searchTerm = signal<string>('');

    private readonly hasBucket = (b: UsageBucket) => this.draftBuckets().has(b);

    private readonly toggleBucket = (b: UsageBucket) => {
        const next = new Set(this.draftBuckets());
        if (next.has(b)) next.delete(b);
        else {
            next.add(b);
            if (this.draftUnusedOnly()) this.draftUnusedOnly.set(false);
        }
        this.draftBuckets.set(next);
    };

    private readonly toggleUnused = () => {
        const next = !this.draftUnusedOnly();
        this.draftUnusedOnly.set(next);
        if (next && this.draftBuckets().size > 0) this.draftBuckets.set(new Set());
    };

    private readonly toggleSourceBuiltIn = () => {
        const next = !this.draftSourceBuiltIn();
        this.draftSourceBuiltIn.set(next);
        if (next && this.draftSourceCustom()) this.draftSourceCustom.set(false);
    };

    private readonly toggleSourceCustom = () => {
        const next = !this.draftSourceCustom();
        this.draftSourceCustom.set(next);
        if (next && this.draftSourceBuiltIn()) this.draftSourceBuiltIn.set(false);
    };

    protected readonly sections = computed<FilterSection[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const match = (label: string) => !term || label.toLowerCase().includes(term);

        const raw: FilterSection[] = [
            {
                title: 'Status',
                items: [
                    {
                        key: 'favorite',
                        label: 'Favorite',
                        checked: () => this.draftFavorite(),
                        toggle: () => this.draftFavorite.update((v) => !v),
                    },
                ],
            },
        ];
        if (this.showSource()) {
            raw.push({
                title: 'Source',
                items: [
                    {
                        key: 'source_built_in',
                        label: 'Build In',
                        checked: () => this.draftSourceBuiltIn(),
                        toggle: () => this.toggleSourceBuiltIn(),
                    },
                    {
                        key: 'source_custom',
                        label: 'Custom',
                        checked: () => this.draftSourceCustom(),
                        toggle: () => this.toggleSourceCustom(),
                    },
                ],
            });
        }
        raw.push({
            title: 'Usage',
            items: [
                {
                    key: 'agent',
                    label: 'Used as Agent Tools',
                    checked: () => this.hasBucket('agent_surface'),
                    toggle: () => this.toggleBucket('agent_surface'),
                },
                {
                    key: 'shared',
                    label: 'Used as Shared Tools',
                    checked: () => this.hasBucket('shared_surface'),
                    toggle: () => this.toggleBucket('shared_surface'),
                },
                {
                    key: 'inline',
                    label: 'Used locally in Flows',
                    checked: () => this.hasBucket('inline_surface'),
                    toggle: () => this.toggleBucket('inline_surface'),
                },
                {
                    key: 'unused',
                    label: 'Not Used',
                    checked: () => this.draftUnusedOnly(),
                    toggle: () => this.toggleUnused(),
                },
            ],
        });

        return raw
            .map((s) => ({ ...s, items: s.items.filter((i) => match(i.label)) }))
            .filter((s) => s.items.length > 0);
    });

    protected readonly showAdvanced = computed<{ includeExclude: boolean; customFilter: boolean }>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        return {
            includeExclude: !term || 'include / exclude'.includes(term),
            customFilter: !term || 'custom filter'.includes(term),
        };
    });

    constructor() {
        effect(() => {
            const init = this.initial();
            this.draftFavorite.set(init.showFavoriteOnly);
            this.draftSourceBuiltIn.set(init.sourceBuiltIn);
            this.draftSourceCustom.set(init.sourceCustom);
            this.draftBuckets.set(new Set(init.usageBuckets));
            this.draftUnusedOnly.set(init.unusedOnly);
        });
    }

    protected onSave(): void {
        this.save.emit({
            showFavoriteOnly: this.draftFavorite(),
            sourceBuiltIn: this.draftSourceBuiltIn(),
            sourceCustom: this.draftSourceCustom(),
            usageBuckets: [...this.draftBuckets()],
            unusedOnly: this.draftUnusedOnly(),
        });
    }

    protected onCancel(): void {
        this.cancel.emit();
    }

    protected onClear(): void {
        this.draftFavorite.set(EMPTY_TOOLS_FILTER.showFavoriteOnly);
        this.draftSourceBuiltIn.set(EMPTY_TOOLS_FILTER.sourceBuiltIn);
        this.draftSourceCustom.set(EMPTY_TOOLS_FILTER.sourceCustom);
        this.draftBuckets.set(new Set());
        this.draftUnusedOnly.set(EMPTY_TOOLS_FILTER.unusedOnly);
        this.clear.emit();
    }

    protected onOpenIncludeExclude(): void {
        this.openIncludeExclude.emit();
    }

    protected onOpenCustomFilter(): void {
        this.openCustomFilter.emit();
    }
}
