import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    EventEmitter,
    Input,
    OnChanges,
    OnInit,
    Output,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Variable } from '../models/variable.model';

@Component({
    selector: 'app-variables-content',
    standalone: true,
    imports: [CommonModule, FormsModule],
    templateUrl: './variables-content.component.html',
    styleUrls: ['./variables-content.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VariablesContentComponent implements OnInit, OnChanges {
    @Input() public variables: Variable[] = [];
    @Output() public variablesChange = new EventEmitter<Variable[]>();

    @ViewChild('nameInput') private nameInput!: ElementRef;

    private internalVariables: Variable[] = [];
    public newVariable: Variable = { name: '', value: '' };
    public editingVariable: Variable = { name: '', value: '' };
    public editingIndex: number = -1;

    public submitted = false;
    public duplicateVariableName: string | null = null;

    constructor(private cdr: ChangeDetectorRef) {}

    public ngOnInit(): void {
        this.internalVariables = [...this.variables];
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['variables'] && !changes['variables'].firstChange) {
            this.internalVariables = [...this.variables];
            this.cdr.markForCheck();
        }
    }

    public onAddVariable(): void {
        this.submitted = true;

        // Check if name is provided
        if (!this.newVariable.name) {
            // Show validation errors
            setTimeout(() => {
                this.submitted = false;
                this.cdr.markForCheck();
            }, 2000);
            return;
        }

        if (this.isDuplicateName(this.newVariable.name)) {
            this.duplicateVariableName = this.newVariable.name;
            setTimeout(() => {
                this.duplicateVariableName = null;
                this.cdr.markForCheck();
            }, 2000);
            return;
        }

        // Add the variable - value can be empty
        this.internalVariables = [...this.internalVariables, { ...this.newVariable }];

        // Emit change event
        this.variablesChange.emit(this.internalVariables);

        // Reset form
        this.newVariable = { name: '', value: '' };
        this.submitted = false;

        // Focus back on the name input
        setTimeout(() => {
            if (this.nameInput) {
                this.nameInput.nativeElement.focus();
            }
            this.cdr.markForCheck();
        }, 0);
    }

    public onRemoveVariable(variable: Variable): void {
        this.internalVariables = this.internalVariables.filter((v) => v.name !== variable.name);
        this.variablesChange.emit(this.internalVariables);
        this.cdr.markForCheck();
    }

    public onEditVariable(index: number): void {
        // Cancel any ongoing edit
        if (this.editingIndex !== -1) {
            this.onCancelEdit();
        }

        // Start a new edit
        this.editingIndex = index;
        this.editingVariable = { ...this.internalVariables[index] };
        this.cdr.markForCheck();
    }

    public onSaveEdit(): void {
        // Only name is required
        if (!this.editingVariable.name) {
            return;
        }

        // Check for duplicate names
        if (this.isDuplicateName(this.editingVariable.name, this.editingIndex)) {
            this.duplicateVariableName = this.editingVariable.name;
            setTimeout(() => {
                this.duplicateVariableName = null;
                this.cdr.markForCheck();
            }, 2000);
            return;
        }

        // Update the variable
        this.internalVariables = this.internalVariables.map((variable, index) => {
            if (index === this.editingIndex) {
                return { ...this.editingVariable };
            }
            return variable;
        });

        // Emit change event
        this.variablesChange.emit(this.internalVariables);

        // Reset editing state
        this.editingIndex = -1;
        this.editingVariable = { name: '', value: '' };
        this.cdr.markForCheck();
    }

    public onCancelEdit(): void {
        this.editingIndex = -1;
        this.editingVariable = { name: '', value: '' };
        this.cdr.markForCheck();
    }

    public isDuplicateName(name: string, excludeIndex: number = -1): boolean {
        if (!name) return false;

        return this.internalVariables.some(
            (variable, index) => variable.name.toLowerCase() === name.toLowerCase() && index !== excludeIndex
        );
    }

    public getVariables(): Variable[] {
        return this.internalVariables;
    }
}
