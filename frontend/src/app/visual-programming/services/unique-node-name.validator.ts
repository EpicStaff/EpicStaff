import { computed, inject, Injectable } from '@angular/core';
import { AbstractControl, AsyncValidatorFn, ValidationErrors } from '@angular/forms';
import { Observable, of } from 'rxjs';

import { FlowService } from './flow.service';

export interface UniqueNameValidationResult {
    isValid: boolean;
    message?: string;
}

@Injectable({
    providedIn: 'root',
})
export class UniqueNodeNameValidatorService {
    private flowService = inject(FlowService);

    // Signal to track all node names for reactive validation
    private nodeNamesSignal = computed(() => {
        return this.flowService.nodes().map((node) => ({
            id: node.id,
            name: node.node_name,
        }));
    });

    // Signal to track all node names for reactive validation (excluding groups)
    public allNamesSignal = computed(() => {
        const nodeNames = this.nodeNamesSignal();

        return nodeNames.map((item) => ({
            id: item.id,
            name: item.name,
            type: 'node' as const,
        }));
    });

    /**
     * Creates an async validator function for unique node names
     * @param currentNodeId - The ID of the current node being edited (to exclude from uniqueness check)
     * @returns AsyncValidatorFn
     */
    public createUniqueNameValidator(currentNodeId?: string): AsyncValidatorFn {
        return (control: AbstractControl): Observable<ValidationErrors | null> => {
            const nodeName = control.value;

            if (!nodeName || typeof nodeName !== 'string') {
                return of(null);
            }

            const trimmedName = nodeName.trim();

            if (!trimmedName) {
                return of({ required: true });
            }

            // Check for uniqueness
            const allNames = this.allNamesSignal();
            const isDuplicate = allNames.some((item) => item.name === trimmedName && item.id !== currentNodeId);

            if (isDuplicate) {
                return of({
                    notUnique: {
                        message: `Node name "${trimmedName}" is already used in this flow`,
                    },
                });
            }

            return of(null);
        };
    }

    /**
     * Synchronous validator for immediate feedback
     * @param currentNodeId - The ID of the current node being edited
     * @returns ValidatorFn
     */
    public createSyncUniqueNameValidator(currentNodeId?: string) {
        return (control: AbstractControl): ValidationErrors | null => {
            const nodeName = control.value;

            if (!nodeName || typeof nodeName !== 'string') {
                return null;
            }

            const trimmedName = nodeName.trim();

            if (!trimmedName) {
                return { required: true };
            }

            // Check for uniqueness
            const allNames = this.allNamesSignal();
            const isDuplicate = allNames.some((item) => item.name === trimmedName && item.id !== currentNodeId);

            if (isDuplicate) {
                return {
                    notUnique: {
                        message: `Node name "${trimmedName}" is already used in this flow`,
                    },
                };
            }

            return null;
        };
    }

    /**
     * Checks if a name is unique in the current flow
     * @param name - The name to check
     * @param excludeId - ID to exclude from the check (current node being edited)
     * @returns boolean
     */
    public isNameUnique(name: string, excludeId?: string): boolean {
        if (!name || typeof name !== 'string') {
            return false;
        }

        const trimmedName = name.trim();
        const allNames = this.allNamesSignal();

        return !allNames.some((item) => item.name === trimmedName && item.id !== excludeId);
    }

    /**
     * Gets all existing node names in the flow (for debugging or display purposes)
     * @returns Array of name objects
     */
    public getAllNames(): Array<{
        id: string;
        name: string;
        type: 'node';
    }> {
        return this.allNamesSignal();
    }

    /**
     * Validates multiple node names at once (useful for paste operations)
     * @param nodeNames - Array of node names to validate
     * @param excludeIds - Array of node IDs to exclude from uniqueness check
     * @returns Object with validation results for each name
     */
    public validateMultipleNodeNames(
        nodeNames: string[],
        excludeIds: string[] = []
    ): Record<string, { isValid: boolean; message?: string }> {
        const allNames = this.allNamesSignal();
        const excludeIdSet = new Set(excludeIds);
        const results: Record<string, { isValid: boolean; message?: string }> = {};

        nodeNames.forEach((name, index) => {
            const trimmedName = name?.trim();

            if (!trimmedName) {
                results[index] = {
                    isValid: false,
                    message: 'Node name is required',
                };
                return;
            }

            // Check for uniqueness
            const isDuplicate = allNames.some((item) => item.name === trimmedName && !excludeIdSet.has(item.id));

            if (isDuplicate) {
                results[index] = {
                    isValid: false,
                    message: `Node name "${trimmedName}" is already used in this flow`,
                };
            } else {
                results[index] = { isValid: true };
            }
        });

        return results;
    }

    /**
     * Gets validation error message for a given error object
     * @param errors - Validation errors object
     * @returns Error message string
     */
    public getValidationErrorMessage(errors: ValidationErrors | null): string {
        if (!errors) {
            return '';
        }

        if (errors['required']) {
            return 'Node name is required';
        }

        if (errors['notUnique']) {
            return errors['notUnique'].message || 'Node name must be unique';
        }

        return 'Invalid node name';
    }
}
