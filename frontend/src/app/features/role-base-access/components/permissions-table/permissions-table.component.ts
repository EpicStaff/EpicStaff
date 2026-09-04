import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, input, output, signal } from '@angular/core';
import { AppSvgIconComponent, ButtonComponent, CheckboxComponent, SearchComponent } from '@shared/components';
import { ActionCode, CatalogAction, CatalogResourceType, CatalogResponse, ResourceCode } from '@shared/models';

import { ACTION_ICONS, GROUP_META, GroupMeta, RESOURCE_META } from '../../constants/permission-table.constant';

interface CatalogGroup {
    key: string;
    label: string;
    icon: string;
    resources: CatalogResourceType[];
}

type TriState = 'checked' | 'indeterminate' | 'empty';

@Component({
    selector: 'app-permissions-table',
    templateUrl: './permissions-table.component.html',
    styleUrls: ['./permissions-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, SearchComponent, CheckboxComponent, ButtonComponent],
})
export class PermissionsTableComponent {
    catalog = input.required<CatalogResponse>();
    selectedPermissions = input.required<Set<string>>();
    readonly = input(false);
    /** Set of `${resource}:${action}` keys the actor is NOT allowed to grant (ceiling rule).
     *  Ignored in readonly mode (all cells are already non-interactive). */
    disabledPermissions = input<Set<string>>(new Set<string>());

    permissionToggle = output<{ resourceType: ResourceCode; action: ActionCode }>();
    /** Toggles ALL applicable & grantable actions for a resource on/off. */
    resourceToggle = output<{ resourceCode: ResourceCode; select: boolean }>();
    /** Toggles ALL applicable & grantable actions across every resource in a group. */
    groupToggle = output<{ groupKey: string; select: boolean }>();
    /** Toggles a single action across every applicable & grantable resource in a group. */
    groupActionToggle = output<{ groupKey: string; actionCode: ActionCode; select: boolean }>();
    selectAllClick = output<void>();
    clearAllClick = output<void>();
    /** Adds the missing recommended keys triggered by a specific resource to the selection. */
    enableRecommendedForResource = output<{ resourceCode: ResourceCode; keys: string[] }>();

    private readonly hostEl = inject<ElementRef<HTMLElement>>(ElementRef);

    searchTerm = signal('');
    collapsedGroups = signal<Set<string>>(new Set());
    /** Resource codes whose recommendation banner the user dismissed within this dialog session.
     *  Only hides the banner UI — yellow borders on recommended checkboxes remain visible. */
    dismissedResources = signal<Set<ResourceCode>>(new Set());

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

    private readonly relations = computed<Record<string, string[]>>(() => {
        const map: Record<string, string[]> = {};
        for (const rt of this.catalog().resource_types) {
            for (const [action, cells] of Object.entries(rt.recommended_with)) {
                map[`${rt.code}:${action}`] = cells.map((c) => `${c.resource_type}:${c.action}`);
            }
        }
        return map;
    });

    readonly recommendedByResource = computed<Map<ResourceCode, { triggers: string[]; missingKeys: string[] }>>(() => {
        if (this.readonly()) return new Map();
        const selected = this.selectedPermissions();
        const disabled = this.disabledPermissions();
        const applicable = this.applicableKeySet();
        const relations = this.relations();
        const acc = new Map<ResourceCode, { triggers: Set<string>; missing: Set<string> }>();
        for (const trigger of selected) {
            const deps = relations[trigger];
            if (!deps || deps.length === 0) continue;
            const missing: string[] = [];
            for (const dep of deps) {
                if (selected.has(dep)) continue;
                if (disabled.has(dep)) continue;
                if (!applicable.has(dep)) continue;
                missing.push(dep);
            }
            if (missing.length === 0) continue;
            const resource = trigger.split(':')[0] as ResourceCode;
            const entry = acc.get(resource) ?? { triggers: new Set<string>(), missing: new Set<string>() };
            entry.triggers.add(trigger);
            for (const k of missing) entry.missing.add(k);
            acc.set(resource, entry);
        }
        const result = new Map<ResourceCode, { triggers: string[]; missingKeys: string[] }>();
        for (const [k, v] of acc) result.set(k, { triggers: [...v.triggers], missingKeys: [...v.missing] });
        return result;
    });

    /** Union of all missing recommended keys — drives yellow highlighting and the global pending count. */
    readonly recommendedSet = computed<Set<string>>(() => {
        const set = new Set<string>();
        for (const entry of this.recommendedByResource().values()) {
            for (const key of entry.missingKeys) set.add(key);
        }
        return set;
    });

    readonly globalPendingCount = computed(() => this.recommendedSet().size);

    /** Next resource (in catalog order) that has pending recommendations. Dismiss does not affect this. */
    readonly nextPendingResourceCode = computed<ResourceCode | null>(() => {
        const byResource = this.recommendedByResource();
        for (const rt of this.catalog().resource_types) {
            if (byResource.has(rt.code)) return rt.code;
        }
        return null;
    });

    /** Whether the recommendation banner for this resource has been dismissed. */
    isBannerDismissed(resourceCode: ResourceCode): boolean {
        return this.dismissedResources().has(resourceCode);
    }

    private readonly applicableKeySet = computed<Set<string>>(() => {
        const set = new Set<string>();
        for (const rt of this.catalog().resource_types) {
            for (const action of rt.applicable_actions) {
                set.add(`${rt.code}:${action}`);
            }
        }
        return set;
    });

    private readonly resourceToGroupMap = computed<Map<ResourceCode, string>>(() => {
        const map = new Map<ResourceCode, string>();
        for (const rt of this.catalog().resource_types) map.set(rt.code, rt.group);
        return map;
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

    isChecked(resourceCode: ResourceCode, actionCode: ActionCode): boolean {
        return this.selectedPermissions().has(`${resourceCode}:${actionCode}`);
    }

    isCellDisabled(resourceCode: ResourceCode, actionCode: ActionCode): boolean {
        return this.readonly() || this.disabledPermissions().has(`${resourceCode}:${actionCode}`);
    }

    isRecommended(resourceCode: ResourceCode, actionCode: ActionCode): boolean {
        return this.recommendedSet().has(`${resourceCode}:${actionCode}`);
    }

    /** Tri-state for a single resource row. Considers only grantable actions. */
    resourceState(resource: CatalogResourceType): TriState {
        const selected = this.selectedPermissions();
        const disabled = this.disabledPermissions();
        let grantable = 0;
        let sel = 0;
        for (const action of resource.applicable_actions) {
            const key = `${resource.code}:${action}`;
            if (disabled.has(key)) continue;
            grantable++;
            if (selected.has(key)) sel++;
        }
        if (grantable === 0 || sel === 0) return 'empty';
        if (sel === grantable) return 'checked';
        return 'indeterminate';
    }

    /** Tri-state for a group header checkbox. Considers only grantable actions in the group. */
    groupState(group: CatalogGroup): TriState {
        const selected = this.selectedPermissions();
        const disabled = this.disabledPermissions();
        let grantable = 0;
        let sel = 0;
        for (const rt of group.resources) {
            for (const action of rt.applicable_actions) {
                const key = `${rt.code}:${action}`;
                if (disabled.has(key)) continue;
                grantable++;
                if (selected.has(key)) sel++;
            }
        }
        if (grantable === 0 || sel === 0) return 'empty';
        if (sel === grantable) return 'checked';
        return 'indeterminate';
    }

    /** Whether the row-checkbox should render as fully-checked (drives the `checked` input). */
    resourceCheckboxChecked(resource: CatalogResourceType): boolean {
        return this.resourceState(resource) === 'checked';
    }

    resourceCheckboxIndeterminate(resource: CatalogResourceType): boolean {
        return this.resourceState(resource) === 'indeterminate';
    }

    groupCheckboxChecked(group: CatalogGroup): boolean {
        return this.groupState(group) === 'checked';
    }

    groupCheckboxIndeterminate(group: CatalogGroup): boolean {
        return this.groupState(group) === 'indeterminate';
    }

    /** Tri-state for a single action across all resources of a group. Considers only applicable & grantable cells. */
    groupActionState(group: CatalogGroup, actionCode: ActionCode): TriState {
        const selected = this.selectedPermissions();
        const disabled = this.disabledPermissions();
        let grantable = 0;
        let sel = 0;
        for (const rt of group.resources) {
            if (!rt.applicable_actions.includes(actionCode)) continue;
            const key = `${rt.code}:${actionCode}`;
            if (disabled.has(key)) continue;
            grantable++;
            if (selected.has(key)) sel++;
        }
        if (grantable === 0 || sel === 0) return 'empty';
        if (sel === grantable) return 'checked';
        return 'indeterminate';
    }

    groupActionCheckboxChecked(group: CatalogGroup, actionCode: ActionCode): boolean {
        return this.groupActionState(group, actionCode) === 'checked';
    }

    groupActionCheckboxIndeterminate(group: CatalogGroup, actionCode: ActionCode): boolean {
        return this.groupActionState(group, actionCode) === 'indeterminate';
    }

    /** Whether the group has at least one applicable & grantable cell for this action. */
    hasGroupApplicableAction(group: CatalogGroup, actionCode: ActionCode): boolean {
        const disabled = this.disabledPermissions();
        for (const rt of group.resources) {
            if (!rt.applicable_actions.includes(actionCode)) continue;
            if (!disabled.has(`${rt.code}:${actionCode}`)) return true;
        }
        return false;
    }

    /** Bulk-action click: toggle the action across every applicable & grantable resource in the group. */
    onGroupActionToggleClick(group: CatalogGroup, actionCode: ActionCode): void {
        if (this.readonly()) return;
        const select = this.groupActionState(group, actionCode) !== 'checked';
        this.groupActionToggle.emit({ groupKey: group.key, actionCode, select });
    }

    /** Row-checkbox click: any non-checked state selects everything grantable; fully-checked clears the row. */
    onResourceRowToggle(resource: CatalogResourceType): void {
        if (this.readonly()) return;
        const select = this.resourceState(resource) !== 'checked';
        this.resourceToggle.emit({ resourceCode: resource.code, select });
    }

    /** BULK SELECT row leading checkbox: toggle every applicable & grantable action in the group. */
    onGroupBulkToggle(group: CatalogGroup): void {
        if (this.readonly()) return;
        const select = this.groupState(group) !== 'checked';
        this.groupToggle.emit({ groupKey: group.key, select });
    }

    resourceDescription(resourceCode: ResourceCode): string {
        return RESOURCE_META[resourceCode]?.description ?? '';
    }

    actionLabel(action: CatalogAction): string {
        return action.label || action.code.charAt(0).toUpperCase() + action.code.slice(1);
    }

    actionIcon(action: CatalogAction): string {
        return ACTION_ICONS[action.code] ?? 'circle';
    }

    keyLabel(key: string): string {
        const [resource, action] = key.split(':');
        const rt = this.catalog().resource_types.find((r) => r.code === resource);
        const act = this.catalog().actions.find((a) => a.code === action);
        const resourceLabel = rt?.label ?? resource;
        const actionLabel = act?.label ?? action;
        return `${resourceLabel}: ${actionLabel}`;
    }

    onEnableResourceRecommended(resourceCode: ResourceCode): void {
        const entry = this.recommendedByResource().get(resourceCode);
        if (!entry || entry.missingKeys.length === 0) return;
        this.enableRecommendedForResource.emit({ resourceCode, keys: entry.missingKeys });
    }

    onDismissResourceRecommended(resourceCode: ResourceCode): void {
        this.dismissedResources.update((set) => {
            if (set.has(resourceCode)) return set;
            const next = new Set(set);
            next.add(resourceCode);
            return next;
        });
    }

    onShowNextPending(): void {
        const resourceCode = this.nextPendingResourceCode();
        if (!resourceCode) return;
        const groupKey = this.resourceToGroupMap().get(resourceCode);
        if (groupKey) {
            this.collapsedGroups.update((set) => {
                if (!set.has(groupKey)) return set;
                const next = new Set(set);
                next.delete(groupKey);
                return next;
            });
        }
        queueMicrotask(() => {
            const host = this.hostEl.nativeElement;
            const el = host.querySelector<HTMLElement>(`[data-resource-code="${resourceCode}"]`);
            el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }

    readonly gridTemplate = computed(() => `24px minmax(280px, 1fr) repeat(${this.catalog().actions.length}, 100px)`);
}
