import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { AppSvgIconComponent, CheckboxComponent, SearchComponent } from '@shared/components';
import { CatalogAction, CatalogResourceType, CatalogResponse } from '@shared/models';

import { ACTION_ICONS, GROUP_META, GroupMeta, RESOURCE_META } from '../../constants/permission-table.constant';

interface CatalogGroup {
    key: string;
    label: string;
    icon: string;
    resources: CatalogResourceType[];
}

@Component({
    selector: 'app-permissions-table',
    templateUrl: './permissions-table.component.html',
    styleUrls: ['./permissions-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, SearchComponent, CheckboxComponent],
})
export class PermissionsTableComponent {
    catalog = input.required<CatalogResponse>();
    selectedPermissions = input.required<Set<string>>();
    readonly = input(false);

    permissionToggle = output<{ resourceType: string; action: string }>();
    selectAllClick = output<void>();
    clearAllClick = output<void>();
    groupSelectAllClick = output<string>();
    groupClearClick = output<string>();

    searchTerm = signal('');
    collapsedGroups = signal<Set<string>>(new Set());

    totalSelected = computed(() => this.selectedPermissions().size);

    private readonly groupedCatalog = computed<CatalogGroup[]>(() => {
        const catalog = this.catalog();
        const groupMap = new Map<string, CatalogResourceType[]>();
        for (const rt of catalog.resource_types) {
            const arr = groupMap.get(rt.group) ?? [];
            arr.push(rt);
            groupMap.set(rt.group, arr);
        }
        return Array.from(groupMap.entries()).map(([key, resources]) => {
            const meta: GroupMeta = GROUP_META[key] ?? { label: key, icon: 'settings' };
            return { key, label: meta.label, icon: meta.icon, resources };
        });
    });

    filteredGroups = computed<CatalogGroup[]>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return this.groupedCatalog();
        return this.groupedCatalog()
            .map((g) => ({
                ...g,
                resources: g.resources.filter((r) => {
                    const desc = RESOURCE_META[r.code]?.description ?? '';
                    return r.label.toLowerCase().includes(term) || desc.toLowerCase().includes(term);
                }),
            }))
            .filter((g) => g.resources.length > 0);
    });

    groupCounts = computed(() => {
        const selected = this.selectedPermissions();
        return new Map(
            this.groupedCatalog().map((g) => {
                let total = 0;
                let selectedCount = 0;
                for (const rt of g.resources) {
                    for (const action of rt.applicable_actions) {
                        total++;
                        if (selected.has(`${rt.code}:${action}`)) selectedCount++;
                    }
                }
                return [g.key, { selected: selectedCount, total }];
            })
        );
    });

    isGroupCollapsed(groupKey: string): boolean {
        return this.collapsedGroups().has(groupKey);
    }

    toggleGroup(groupKey: string): void {
        this.collapsedGroups.update((set) => {
            const next = new Set(set);
            next.has(groupKey) ? next.delete(groupKey) : next.add(groupKey);
            return next;
        });
    }

    isApplicable(resource: CatalogResourceType, action: CatalogAction): boolean {
        return resource.applicable_actions.includes(action.code);
    }

    isChecked(resourceCode: string, actionCode: string): boolean {
        return this.selectedPermissions().has(`${resourceCode}:${actionCode}`);
    }

    resourceDescription(resourceCode: string): string {
        return RESOURCE_META[resourceCode]?.description ?? '';
    }

    actionLabel(action: CatalogAction): string {
        return action.label || action.code.charAt(0).toUpperCase() + action.code.slice(1);
    }

    actionIcon(action: CatalogAction): string {
        return ACTION_ICONS[action.code] ?? 'circle';
    }

    readonly gridTemplate = computed(() => `minmax(300px, 1fr) repeat(${this.catalog().actions.length}, 100px)`);
}
