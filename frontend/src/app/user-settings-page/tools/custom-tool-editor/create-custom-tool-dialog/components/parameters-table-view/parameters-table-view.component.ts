import { CdkDragDrop } from '@angular/cdk/drag-drop';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    input,
    OnInit,
    output,
    signal,
    untracked,
    viewChildren,
} from '@angular/core';

import { TableRow } from '../../../../../../shared/components/dynamic-table/dynamic-table.models';
import {
    rowDataToVariable,
    ToolVariable,
    validateVariablesTree,
    VARIABLE_SECTIONS,
    VariableInputType,
    variableToRowData,
} from '../parameters-table.config';
import { VariableSectionComponent, VariableSectionMode } from '../variable-section/variable-section.component';
import { BreadcrumbItem, VariablesBreadcrumbComponent } from '../variables-breadcrumb/variables-breadcrumb.component';

export type DrillStepKind = 'object' | 'array';

export interface DrillStep {
    sectionType: VariableInputType;
    /** Index into the currently-displayed rows when this step was created. Always 0 for steps inside an array sub-view (only one synthesized row). */
    rowIndex: number;
    label: string;
    kind: DrillStepKind;
}

const ITEM_ROW_NAME = 'item';

@Component({
    selector: 'app-parameters-table-view',
    imports: [VariablesBreadcrumbComponent, VariableSectionComponent],
    templateUrl: './parameters-table-view.component.html',
    styleUrls: ['./parameters-table-view.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ParametersTableViewComponent implements OnInit {
    variables = input.required<ToolVariable[]>();
    initialDrillStack = input<DrillStep[]>([]);
    variablesChange = output<ToolVariable[]>();
    drillStackChange = output<DrillStep[]>();

    readonly VARIABLE_SECTIONS = VARIABLE_SECTIONS;

    readonly parameterRowDropConnectedIds = ['ptv-user', 'ptv-agent', 'ptv-mixed'] as const;

    readonly parameterRowSyncRevision = signal(0);

    private readonly sectionRefs = viewChildren(VariableSectionComponent);

    private readonly userVariables = signal<ToolVariable[]>([]);
    private readonly agentVariables = signal<ToolVariable[]>([]);
    private readonly mixedVariables = signal<ToolVariable[]>([]);

    private readonly drillStack = signal<DrillStep[]>([]);

    public readonly crumbs = computed<BreadcrumbItem[]>(() => {
        const stack = this.drillStack();
        return [
            { icon: 'home', label: '' },
            ...stack.map((step) => ({
                icon: step.kind === 'array' ? 'square-brackets' : 'brackets',
                label: step.label,
            })),
        ];
    });

    public readonly isDrilling = computed(() => this.drillStack().length > 0);

    public readonly currentSectionType = computed<VariableInputType | null>(() => {
        const stack = this.drillStack();
        return stack.length > 0 ? stack[0].sectionType : null;
    });

    public readonly currentDrillSectionConfig = computed(() => {
        const sectionType = this.currentSectionType();
        return sectionType ? this.getSectionConfig(sectionType) : null;
    });

    public readonly currentDrillMode = computed<VariableSectionMode>(() => {
        const stack = this.drillStack();
        const last = stack[stack.length - 1];
        return last?.kind === 'array' ? 'array-values' : 'rows';
    });

    public readonly currentDrillRows = computed<Record<string, unknown>[]>(() =>
        this.getVariablesAtCurrentDrill().map(variableToRowData)
    );

    public readonly externalDuplicatesByType = computed<Record<VariableInputType, Map<string, Set<string>>>>(() => {
        const userNames = this.collectNames(this.userVariables());
        const agentNames = this.collectNames(this.agentVariables());
        const mixedNames = this.collectNames(this.mixedVariables());

        return {
            user_input: new Map([['name', this.unionSets(agentNames, mixedNames)]]),
            agent_input: new Map([['name', this.unionSets(userNames, mixedNames)]]),
            mixed: new Map([['name', this.unionSets(userNames, agentNames)]]),
        };
    });

    validate(): void {
        for (const section of this.sectionRefs()) {
            section.validate();
        }
    }

    isValid(): boolean {
        if (!this.sectionRefs().every((section) => section.isValid())) {
            return false;
        }

        const user = this.userVariables();
        const agent = this.agentVariables();
        const mixed = this.mixedVariables();
        if (!validateVariablesTree(user) || !validateVariablesTree(agent) || !validateVariablesTree(mixed)) {
            return false;
        }

        const topNames = [...user, ...agent, ...mixed].map((v) => v.name?.trim()).filter(Boolean) as string[];
        if (new Set(topNames).size !== topNames.length) {
            return false;
        }

        return true;
    }

    ngOnInit(): void {
        const source = this.variables();
        this.userVariables.set(source.filter((v) => v.input_type === 'user_input'));
        this.agentVariables.set(source.filter((v) => v.input_type === 'agent_input'));
        this.mixedVariables.set(source.filter((v) => v.input_type === 'mixed'));
        this.drillStack.set(this.coerceDrillStack(this.initialDrillStack()));
    }

    constructor() {
        effect(() => {
            const stack = this.drillStack();
            untracked(() => this.drillStackChange.emit(stack));
        });
    }

    getSectionInitialRows(type: VariableInputType): Record<string, unknown>[] {
        return this.getSectionVariables(type).map(variableToRowData);
    }

    onSectionRowsChange(type: VariableInputType, rows: Record<string, unknown>[]): void {
        this.setSectionVariables(
            type,
            rows.map((data) => rowDataToVariable(data, type))
        );
        this.emitAll();
    }

    parameterRowDropListId(type: VariableInputType): string | null {
        return this.isDrilling() ? null : this.parameterDropIdForType(type);
    }

    parameterRowDropConnectedTo(): string[] {
        return this.isDrilling() ? [] : [...this.parameterRowDropConnectedIds];
    }

    onCrossListDrop(event: CdkDragDrop<unknown[]>): void {
        const sourceType = this.dropListElementIdToInputType(event.previousContainer.id);
        const targetType = this.dropListElementIdToInputType(event.container.id);
        if (!sourceType || !targetType || sourceType === targetType) {
            return;
        }

        const previousIndex = event.previousIndex;
        const currentIndex = event.currentIndex;

        const sourceVars = [...this.getSectionVariables(sourceType)];
        const targetVars = [...this.getSectionVariables(targetType)];

        if (previousIndex < 0 || previousIndex >= sourceVars.length) {
            return;
        }
        if (currentIndex < 0 || currentIndex > targetVars.length) {
            return;
        }

        const [moved] = sourceVars.splice(previousIndex, 1);
        const transformed = this.applyVariableTargetSection(moved, targetType);
        targetVars.splice(currentIndex, 0, transformed);

        this.setSectionVariables(sourceType, sourceVars);
        this.setSectionVariables(targetType, targetVars);
        this.parameterRowSyncRevision.update((n) => n + 1);
        this.emitAll();
    }

    onNavigate(event: { row: TableRow; rowIndex: number; sectionType: VariableInputType }): void {
        const rowType = event.row.data['type'];
        const kind: DrillStepKind = rowType === 'array' ? 'array' : 'object';
        const baseLabel = String(event.row.data['name'] ?? '');
        const label = baseLabel || (kind === 'array' ? ITEM_ROW_NAME : 'Object');
        const wasDrilling = this.isDrilling();
        this.drillStack.update((stack) => [
            ...stack,
            {
                sectionType: stack.length > 0 ? stack[0].sectionType : event.sectionType,
                rowIndex: event.rowIndex,
                label,
                kind,
            },
        ]);
        if (wasDrilling) {
            this.parameterRowSyncRevision.update((n) => n + 1);
        }
    }

    onCrumbClick(index: number): void {
        if (index === 0) {
            this.drillStack.set([]);
            return;
        }

        this.drillStack.update((stack) => stack.slice(0, index));
        this.parameterRowSyncRevision.update((n) => n + 1);
    }

    onDrillRowsChange(rows: Record<string, unknown>[]): void {
        const sectionType = this.currentSectionType();
        if (!sectionType) {
            return;
        }

        const stack = this.drillStack();

        const children = rows.map((data) => rowDataToVariable(data, sectionType));

        const roots = this.getSectionVariables(sectionType);
        const updatedRoots = setStackOnRoots(roots, stack, children);
        this.setSectionVariables(sectionType, updatedRoots);

        this.emitAll();
    }

    private getSectionVariables(type: VariableInputType): ToolVariable[] {
        switch (type) {
            case 'user_input':
                return this.userVariables();
            case 'agent_input':
                return this.agentVariables();
            case 'mixed':
                return this.mixedVariables();
        }
    }

    private setSectionVariables(type: VariableInputType, vars: ToolVariable[]): void {
        switch (type) {
            case 'user_input':
                this.userVariables.set(vars);
                break;
            case 'agent_input':
                this.agentVariables.set(vars);
                break;
            case 'mixed':
                this.mixedVariables.set(vars);
                break;
        }
    }

    private getSectionConfig(type: VariableInputType) {
        return VARIABLE_SECTIONS.find((section) => section.inputType === type) ?? null;
    }

    private coerceDrillStack(stack: DrillStep[]): DrillStep[] {
        if (!stack || stack.length === 0) {
            return [];
        }

        const sectionType = stack[0].sectionType;
        let cursor: ToolVariable[] = this.getSectionVariables(sectionType);
        const valid: DrillStep[] = [];

        for (const step of stack) {
            if (step.sectionType !== sectionType) break;

            const target = cursor[step.rowIndex];
            if (!target) break;
            if (target.type !== step.kind) break;

            valid.push({
                sectionType,
                rowIndex: step.rowIndex,
                label: String(target.name ?? (step.kind === 'array' ? ITEM_ROW_NAME : 'Object')),
                kind: step.kind,
            });
            cursor = Array.isArray(target.children) ? target.children : [];
        }

        return valid;
    }

    private getVariablesAtCurrentDrill(): ToolVariable[] {
        const stack = this.drillStack();
        if (stack.length === 0) return [];

        const sectionType = stack[0].sectionType;
        let cursor: ToolVariable[] = this.getSectionVariables(sectionType);

        for (let i = 0; i < stack.length; i++) {
            const target = cursor[stack[i].rowIndex];
            if (!target) return [];
            const children = Array.isArray(target.children) ? target.children : [];
            if (i === stack.length - 1) return children;
            cursor = children;
        }

        return [];
    }

    private emitAll(): void {
        this.variablesChange.emit([...this.userVariables(), ...this.agentVariables(), ...this.mixedVariables()]);
    }

    private parameterDropIdForType(type: VariableInputType): string {
        switch (type) {
            case 'user_input':
                return 'ptv-user';
            case 'agent_input':
                return 'ptv-agent';
            case 'mixed':
                return 'ptv-mixed';
        }
    }

    private dropListElementIdToInputType(id: string): VariableInputType | null {
        switch (id) {
            case 'ptv-user':
                return 'user_input';
            case 'ptv-agent':
                return 'agent_input';
            case 'ptv-mixed':
                return 'mixed';
            default:
                return null;
        }
    }

    private applyVariableTargetSection(variable: ToolVariable, target: VariableInputType): ToolVariable {
        return {
            ...variable,
            input_type: target,
            required: target === 'agent_input',
        };
    }

    private collectNames(vars: ToolVariable[]): Set<string> {
        const names = new Set<string>();
        for (const v of vars) {
            const name = v.name?.trim();
            if (name) names.add(name);
        }
        return names;
    }

    private unionSets(a: Set<string>, b: Set<string>): Set<string> {
        const result = new Set<string>(a);
        for (const v of b) result.add(v);
        return result;
    }
}

// --- module-local helpers ---

function setStackOnRoots(roots: ToolVariable[], stack: DrillStep[], children: ToolVariable[]): ToolVariable[] {
    if (stack.length === 0) return roots;
    const [first, ...rest] = stack;
    return roots.map((variable, i) => (i === first.rowIndex ? setChildrenAtPath(variable, rest, children) : variable));
}

function setChildrenAtPath(variable: ToolVariable, rest: DrillStep[], children: ToolVariable[]): ToolVariable {
    if (rest.length === 0) {
        return { ...variable, children };
    }
    const cur = Array.isArray(variable.children) ? variable.children : [];
    const [next, ...rest2] = rest;
    return {
        ...variable,
        children: cur.map((c, i) => (i === next.rowIndex ? setChildrenAtPath(c, rest2, children) : c)),
    };
}
