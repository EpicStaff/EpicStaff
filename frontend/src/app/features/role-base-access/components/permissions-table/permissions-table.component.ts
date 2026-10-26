import { ChangeDetectionStrategy, Component, computed, ElementRef, inject, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, CheckboxComponent, SearchComponent } from '@shared/components';
import { ActionCode, CatalogAction, CatalogResponse } from '@shared/models';

import { ACTION_ICONS } from '../../constants/permission-table.constant';
import { PermissionMatrixGroup, PermissionMatrixRow } from './permission-matrix.model';
import { catalogMatrixGroups, permissionKey } from './permission-matrix.util';

type TriState = 'checked' | 'indeterminate' | 'empty';

@Component({
    selector: 'app-permissions-table',
    templateUrl: './permissions-table.component.html',
    styleUrls: ['./permissions-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, SearchComponent, CheckboxComponent, ButtonComponent, MatTooltipModule],
})
export class PermissionsTableComponent {
    catalog = input.required<CatalogResponse>();
    /** Groups shown after the catalog's groups, with rows extensions add (see `ROLE_PERMISSION_EXTENSIONS`). Their
     *  columns are the catalog's actions; a row shows a cell only for its own actions. */
    extensionGroups = input<readonly PermissionMatrixGroup[]>([]);
    selectedPermissions = input.required<ReadonlySet<string>>();
    readonly = input(false);
    /** Set of `${resource}:${action}` keys the actor is NOT allowed to grant (ceiling rule).
     *  Ignored in readonly mode (all cells are already non-interactive). */
    disabledPermissions = input<ReadonlySet<string>>(new Set<string>());

    /** `resourceType` is the row's code: a catalog resource code or an extension row's code. */
    permissionToggle = output<{ resourceType: string; action: ActionCode }>();
    /** Toggles ALL applicable & grantable actions for a resource on/off. */
    resourceToggle = output<{ resourceCode: string; select: boolean }>();
    /** Toggles ALL applicable & grantable actions across every resource in a group. */
    groupToggle = output<{ groupKey: string; select: boolean }>();
    /** Toggles a single action across every applicable & grantable resource in a group. */
    groupActionToggle = output<{ groupKey: string; actionCode: ActionCode; select: boolean }>();
    selectAllClick = output<void>();
    clearAllClick = output<void>();
    /** Adds the missing recommended keys triggered by a specific resource to the selection. */
    enableRecommendedForResource = output<{ resourceCode: string; keys: string[] }>();

    private readonly hostEl = inject<ElementRef<HTMLElement>>(ElementRef);

    searchTerm = signal('');
    collapsedGroups = signal<Set<string>>(new Set());
    /** Missing-keys signatures whose recommendation banner the user dismissed within this dialog
     *  session. Only hides the banner UI — yellow borders on recommended checkboxes remain visible. */
    dismissedSignatures = signal<Set<string>>(new Set());
    lastToggledResources = signal<Set<string>>(new Set());
    lastShownPendingResourceCode = signal<string | null>(null);

    totalSelected = computed(() => this.selectedPermissions().size);

    private readonly groups = computed<PermissionMatrixGroup[]>(() => [
        ...catalogMatrixGroups(this.catalog()),
        ...this.extensionGroups(),
    ]);

    private readonly allRows = computed<PermissionMatrixRow[]>(() => this.groups().flatMap((group) => group.rows));

    /** The row each cell key belongs to. Row codes may contain `:` themselves, so a key is never split to find it. */
    private readonly rowCodeByKey = computed<Map<string, string>>(() => {
        const map = new Map<string, string>();
        for (const row of this.allRows()) {
            for (const action of row.actions) map.set(permissionKey(row.code, action), row.code);
        }
        return map;
    });

    filteredGroups = computed<PermissionMatrixGroup[]>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        const hideEmpty = this.readonly();
        if (!term && !hideEmpty) return this.groups();
        return this.groups()
            .map((g) => ({
                ...g,
                rows: g.rows.filter((r) => {
                    if (term && !(r.label.toLowerCase().includes(term) || r.description.toLowerCase().includes(term))) {
                        return false;
                    }
                    if (hideEmpty && !this.hasGrantedPermission(r)) return false;
                    return true;
                }),
            }))
            .filter((g) => g.rows.length > 0);
    });

    groupCounts = computed(() => {
        const selected = this.selectedPermissions();
        return new Map(
            this.groups().map((g) => {
                let total = 0;
                let selectedCount = 0;
                for (const row of g.rows) {
                    for (const action of row.actions) {
                        total++;
                        if (selected.has(permissionKey(row.code, action))) selectedCount++;
                    }
                }
                return [g.key, { selected: selectedCount, total }];
            })
        );
    });

    private readonly relations = computed<Record<string, readonly string[]>>(() => {
        const map: Record<string, readonly string[]> = {};
        for (const row of this.allRows()) {
            for (const [action, cells] of Object.entries(row.recommendedWith)) {
                if (cells) map[`${row.code}:${action}`] = cells;
            }
        }
        return map;
    });

    readonly recommendedByResource = computed<Map<string, { triggers: string[]; missingKeys: string[] }>>(() => {
        if (this.readonly()) return new Map();
        const selected = this.selectedPermissions();
        const disabled = this.disabledPermissions();
        const applicable = this.applicableKeySet();
        const relations = this.relations();
        const rowCodeByKey = this.rowCodeByKey();
        const acc = new Map<string, { triggers: Set<string>; missing: Set<string> }>();
        for (const trigger of selected) {
            const deps = relations[trigger];
            if (!deps || deps.length === 0) continue;
            const resource = rowCodeByKey.get(trigger);
            if (resource === undefined) continue;
            const missing: string[] = [];
            for (const dep of deps) {
                if (selected.has(dep)) continue;
                if (disabled.has(dep)) continue;
                if (!applicable.has(dep)) continue;
                missing.push(dep);
            }
            if (missing.length === 0) continue;
            const entry = acc.get(resource) ?? { triggers: new Set<string>(), missing: new Set<string>() };
            entry.triggers.add(trigger);
            for (const k of missing) entry.missing.add(k);
            acc.set(resource, entry);
        }
        const result = new Map<string, { triggers: string[]; missingKeys: string[] }>();
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

    private readonly missingKeysSignatureByResource = computed<Map<string, string>>(() => {
        const map = new Map<string, string>();
        for (const [resourceCode, entry] of this.recommendedByResource()) {
            map.set(resourceCode, [...entry.missingKeys].sort().join('|'));
        }
        return map;
    });

    private readonly consolidationWinners = computed<Set<string>>(() => {
        const lastToggled = this.lastToggledResources();
        const signatures = this.missingKeysSignatureByResource();
        const bySignature = new Map<string, { resourceCode: string; toggled: boolean }>();
        for (const row of this.allRows()) {
            const signature = signatures.get(row.code);
            if (!signature) continue;
            const toggled = lastToggled.has(row.code);
            const existing = bySignature.get(signature);
            if (!existing || (toggled && !existing.toggled)) {
                bySignature.set(signature, { resourceCode: row.code, toggled });
            }
        }
        return new Set([...bySignature.values()].map((winner) => winner.resourceCode));
    });

    readonly consolidatedRecommendations = computed<{ resourceCode: string; missingKeys: string[] }[]>(() => {
        const winners = this.consolidationWinners();
        const result: { resourceCode: string; missingKeys: string[] }[] = [];
        for (const [resourceCode, entry] of this.recommendedByResource()) {
            if (!winners.has(resourceCode)) continue;
            if (this.isBannerDismissed(resourceCode)) continue;
            result.push({ resourceCode, missingKeys: entry.missingKeys });
        }
        return result;
    });

    private readonly visibleRecommendationByResource = computed<Map<string, { missingKeys: string[] }>>(() => {
        const map = new Map<string, { missingKeys: string[] }>();
        for (const entry of this.consolidatedRecommendations()) map.set(entry.resourceCode, entry);
        return map;
    });

    recommendationFor(resourceCode: string): { missingKeys: string[] } | undefined {
        return this.visibleRecommendationByResource().get(resourceCode);
    }

    readonly globalPendingCount = computed(() => this.recommendedSet().size);

    private readonly orderedPendingResourceCodes = computed<string[]>(() => {
        const winners = this.consolidationWinners();
        const codes: string[] = [];
        for (const row of this.allRows()) {
            if (winners.has(row.code) && !this.isBannerDismissed(row.code)) codes.push(row.code);
        }
        return codes;
    });

    readonly nextPendingResourceCode = computed<string | null>(() => {
        const ordered = this.orderedPendingResourceCodes();
        if (ordered.length === 0) return null;
        const lastShown = this.lastShownPendingResourceCode();
        const lastIndex = lastShown === null ? -1 : ordered.indexOf(lastShown);
        return ordered[(lastIndex + 1) % ordered.length];
    });

    private readonly resourceToGroupMap = computed<Map<string, string>>(() => {
        const map = new Map<string, string>();
        for (const group of this.groups()) {
            for (const row of group.rows) map.set(row.code, group.key);
        }
        return map;
    });

    /** A label for every cell key: `<row label>: <action label>`. */
    private readonly cellLabels = computed<Map<string, string>>(() => {
        const actionLabels = new Map(this.catalog().actions.map((action) => [action.code, action.label]));
        const map = new Map<string, string>();
        for (const row of this.allRows()) {
            for (const action of row.actions) {
                map.set(permissionKey(row.code, action), `${row.label}: ${actionLabels.get(action) ?? action}`);
            }
        }
        return map;
    });

    /** Whether the recommendation banner for this resource's missing-keys signature has been dismissed. */
    isBannerDismissed(resourceCode: string): boolean {
        const signature = this.missingKeysSignatureByResource().get(resourceCode);
        return signature !== undefined && this.dismissedSignatures().has(signature);
    }

    private readonly applicableKeySet = computed<Set<string>>(() => new Set(this.rowCodeByKey().keys()));

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

    isApplicable(row: PermissionMatrixRow, action: CatalogAction): boolean {
        return row.actions.includes(action.code);
    }

    isChecked(resourceCode: string, actionCode: ActionCode): boolean {
        return this.selectedPermissions().has(permissionKey(resourceCode, actionCode));
    }

    /** The cell's tooltip: what the action allows on that row, when the row says. */
    cellTooltip(row: PermissionMatrixRow, actionCode: ActionCode): string {
        return row.actionDescriptions[actionCode] ?? '';
    }

    /** The cell checkbox's name, `<row>: <action>`, with the description when the row has one (screen readers do not
     *  read the tooltip). */
    cellAriaLabel(row: PermissionMatrixRow, actionCode: ActionCode): string {
        const name = this.keyLabel(permissionKey(row.code, actionCode));
        const description = this.cellTooltip(row, actionCode);
        return description ? `${name}. ${description}` : name;
    }

    private hasGrantedPermission(row: PermissionMatrixRow): boolean {
        const selected = this.selectedPermissions();
        return row.actions.some((action) => selected.has(permissionKey(row.code, action)));
    }

    isCellDisabled(resourceCode: string, actionCode: ActionCode): boolean {
        return this.readonly() || this.disabledPermissions().has(permissionKey(resourceCode, actionCode));
    }

    isRecommended(resourceCode: string, actionCode: ActionCode): boolean {
        return this.recommendedSet().has(permissionKey(resourceCode, actionCode));
    }

    /** Tri-state for a single resource row. Considers only grantable actions. */
    resourceState(row: PermissionMatrixRow): TriState {
        const selected = this.selectedPermissions();
        const disabled = this.disabledPermissions();
        let grantable = 0;
        let sel = 0;
        for (const action of row.actions) {
            const key = permissionKey(row.code, action);
            if (disabled.has(key)) continue;
            grantable++;
            if (selected.has(key)) sel++;
        }
        if (grantable === 0 || sel === 0) return 'empty';
        if (sel === grantable) return 'checked';
        return 'indeterminate';
    }

    /** Tri-state for a group header checkbox. Considers only grantable actions in the group. */
    groupState(group: PermissionMatrixGroup): TriState {
        const selected = this.selectedPermissions();
        const disabled = this.disabledPermissions();
        let grantable = 0;
        let sel = 0;
        for (const row of group.rows) {
            for (const action of row.actions) {
                const key = permissionKey(row.code, action);
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
    resourceCheckboxChecked(row: PermissionMatrixRow): boolean {
        return this.resourceState(row) === 'checked';
    }

    resourceCheckboxIndeterminate(row: PermissionMatrixRow): boolean {
        return this.resourceState(row) === 'indeterminate';
    }

    groupCheckboxChecked(group: PermissionMatrixGroup): boolean {
        return this.groupState(group) === 'checked';
    }

    groupCheckboxIndeterminate(group: PermissionMatrixGroup): boolean {
        return this.groupState(group) === 'indeterminate';
    }

    /** Tri-state for a single action across all resources of a group. Considers only applicable & grantable cells. */
    groupActionState(group: PermissionMatrixGroup, actionCode: ActionCode): TriState {
        const selected = this.selectedPermissions();
        const disabled = this.disabledPermissions();
        let grantable = 0;
        let sel = 0;
        for (const row of group.rows) {
            if (!row.actions.includes(actionCode)) continue;
            const key = permissionKey(row.code, actionCode);
            if (disabled.has(key)) continue;
            grantable++;
            if (selected.has(key)) sel++;
        }
        if (grantable === 0 || sel === 0) return 'empty';
        if (sel === grantable) return 'checked';
        return 'indeterminate';
    }

    groupActionCheckboxChecked(group: PermissionMatrixGroup, actionCode: ActionCode): boolean {
        return this.groupActionState(group, actionCode) === 'checked';
    }

    groupActionCheckboxIndeterminate(group: PermissionMatrixGroup, actionCode: ActionCode): boolean {
        return this.groupActionState(group, actionCode) === 'indeterminate';
    }

    /** Whether the group has at least one applicable & grantable cell for this action. */
    hasGroupApplicableAction(group: PermissionMatrixGroup, actionCode: ActionCode): boolean {
        const disabled = this.disabledPermissions();
        for (const row of group.rows) {
            if (!row.actions.includes(actionCode)) continue;
            if (!disabled.has(permissionKey(row.code, actionCode))) return true;
        }
        return false;
    }

    /** Bulk-action click: toggle the action across every applicable & grantable resource in the group. */
    onGroupActionToggleClick(group: PermissionMatrixGroup, actionCode: ActionCode, checkbox: CheckboxComponent): void {
        if (this.readonly()) return;
        const select = this.groupActionState(group, actionCode) === 'empty';
        checkbox.checked.set(select);
        const disabled = this.disabledPermissions();
        this.lastToggledResources.set(
            new Set(
                group.rows
                    .filter(
                        (row) => row.actions.includes(actionCode) && !disabled.has(permissionKey(row.code, actionCode))
                    )
                    .map((row) => row.code)
            )
        );
        this.groupActionToggle.emit({ groupKey: group.key, actionCode, select });
    }

    /**
     * Row-checkbox click: an empty row selects everything grantable; a "-" or fully-checked row clears it.
     * Every tri-state handler here sets the box's own state: clicking a "-" box makes the browser tick it,
     * and when the click clears instead, `[checked]` stays false — an unchanged binding Angular won't rewrite.
     */
    onResourceRowToggle(row: PermissionMatrixRow, checkbox: CheckboxComponent): void {
        if (this.readonly()) return;
        const select = this.resourceState(row) === 'empty';
        checkbox.checked.set(select);
        this.lastToggledResources.set(new Set([row.code]));
        this.resourceToggle.emit({ resourceCode: row.code, select });
    }

    /** BULK SELECT row leading checkbox: toggle every applicable & grantable action in the group. */
    onGroupBulkToggle(group: PermissionMatrixGroup, checkbox: CheckboxComponent): void {
        if (this.readonly()) return;
        const select = this.groupState(group) === 'empty';
        checkbox.checked.set(select);
        this.lastToggledResources.set(new Set(group.rows.map((row) => row.code)));
        this.groupToggle.emit({ groupKey: group.key, select });
    }

    onPermissionCellToggle(resourceType: string, action: ActionCode): void {
        this.lastToggledResources.set(new Set([resourceType]));
        this.permissionToggle.emit({ resourceType, action });
    }

    actionLabel(action: CatalogAction): string {
        return action.label || action.code.charAt(0).toUpperCase() + action.code.slice(1);
    }

    actionIcon(action: CatalogAction): string {
        return ACTION_ICONS[action.code] ?? 'circle';
    }

    keyLabel(key: string): string {
        return this.cellLabels().get(key) ?? key;
    }

    onEnableResourceRecommended(resourceCode: string): void {
        const entry = this.recommendedByResource().get(resourceCode);
        if (!entry || entry.missingKeys.length === 0) return;
        this.enableRecommendedForResource.emit({ resourceCode, keys: entry.missingKeys });
    }

    onDismissResourceRecommended(resourceCode: string): void {
        const signature = this.missingKeysSignatureByResource().get(resourceCode);
        if (!signature) return;
        this.dismissedSignatures.update((set) => {
            if (set.has(signature)) return set;
            const next = new Set(set);
            next.add(signature);
            return next;
        });
    }

    onShowNextPending(): void {
        const resourceCode = this.nextPendingResourceCode();
        if (!resourceCode) return;
        this.lastShownPendingResourceCode.set(resourceCode);
        this.lastToggledResources.set(new Set([resourceCode]));
        const groupKey = this.resourceToGroupMap().get(resourceCode);
        if (groupKey) {
            this.collapsedGroups.update((set) => {
                if (!set.has(groupKey)) return set;
                const next = new Set(set);
                next.delete(groupKey);
                return next;
            });
        }
        this.scrollToResourceWhenSettled(resourceCode);
    }

    private scrollRequestId = 0;

    private scrollToResourceWhenSettled(resourceCode: string, deadline = performance.now() + 1000): void {
        const requestId = ++this.scrollRequestId;
        const host = this.hostEl.nativeElement;
        requestAnimationFrame(() => {
            if (requestId !== this.scrollRequestId) return;
            const el = host.querySelector<HTMLElement>(`[data-resource-code="${resourceCode}"]`);
            const container = host.querySelector<HTMLElement>('.perm-table');
            if (!el || !container) return;
            let lastTop = el.getBoundingClientRect().top;
            let stableFrames = 0;
            const step = (): void => {
                if (requestId !== this.scrollRequestId) return;
                const top = el.getBoundingClientRect().top;
                stableFrames = Math.abs(top - lastTop) < 0.5 ? stableFrames + 1 : 0;
                lastTop = top;
                if (stableFrames >= 3 || performance.now() >= deadline) {
                    this.scrollRowUnderStickyHeader(container, el);
                    return;
                }
                requestAnimationFrame(step);
            };
            requestAnimationFrame(step);
        });
    }

    private scrollRowUnderStickyHeader(container: HTMLElement, el: HTMLElement): void {
        const headers = container.querySelector<HTMLElement>('.perm-headers');
        const topBanner = container.querySelector<HTMLElement>('.related-banner.top');
        const stickyOffset =
            (headers?.getBoundingClientRect().height ?? 0) + (topBanner?.getBoundingClientRect().height ?? 0) + 8;
        const currentOffset =
            el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
        container.scrollTo({ top: Math.max(0, currentOffset - stickyOffset), behavior: 'smooth' });
    }

    readonly gridTemplate = computed(() => `24px minmax(280px, 1fr) repeat(${this.catalog().actions.length}, 100px)`);
}
