import { Injectable } from '@angular/core';
import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

import { NodeModel } from '../core/models/node.model';
import { FlowService } from './flow.service';

export interface NodeNameValidationResult {
    isValid: boolean;
    errorMessage?: string;
    existingNode?: NodeModel;
}

/**
 * Service for validating unique node names across all nodes in the flow.
 *
 * This service provides comprehensive node name validation functionality:
 * - Validates uniqueness across all nodes
 * - Supports excluding current node when editing
 * - Provides helpful error messages
 * - Can suggest next available names
 *
 * @example
 * ```typescript
 * // In a component constructor
 * constructor(
 *   private nodeNameValidatorService: NodeNameValidatorService
 * ) {}
 *
 * // In ngOnInit or after @Input is available
 * ngOnInit() {
 *   const nodeNameControl = this.form.get('node_name');
 *   nodeNameControl.setValidators([
 *     Validators.required,
 *     this.nodeNameValidatorService.createUniqueNodeNameValidator(this.node?.id)
 *   ]);
 *   nodeNameControl.updateValueAndValidity();
 * }
 *
 * // Or validate programmatically
 * const result = this.nodeNameValidatorService.validateNodeName('My Node', this.node?.id);
 * if (!result.isValid) {
 *   console.log(result.errorMessage);
 * }
 * ```
 */
@Injectable({
    providedIn: 'root',
})
export class NodeNameValidatorService {
    constructor(private flowService: FlowService) {}

    /**
     * Creates a validator function that checks for unique node names
     * @param excludeNodeId - Optional node ID to exclude from validation (for editing existing nodes)
     * @returns ValidatorFn that can be used in Angular forms
     */
    public createUniqueNodeNameValidator(excludeNodeId?: string): ValidatorFn {
        return (control: AbstractControl): ValidationErrors | null => {
            const value = control.value;
            if (!value) {
                return null; // Let required validator handle empty values
            }

            const nodeName = value.trim();
            if (!nodeName) {
                return null; // Empty after trim, let required validator handle
            }

            const validationResult = this.validateNodeName(nodeName, excludeNodeId);

            if (!validationResult.isValid) {
                return {
                    uniqueNodeName: {
                        message: validationResult.errorMessage || 'Node name must be unique.',
                    },
                };
            }

            return null;
        };
    }

    /**
     * Validates if a node name is unique across all nodes
     * @param nodeName - The node name to validate
     * @param excludeNodeId - Optional node ID to exclude from validation
     * @returns NodeNameValidationResult with validation details
     */
    public validateNodeName(nodeName: string, excludeNodeId?: string): NodeNameValidationResult {
        const nodes = this.flowService.nodes();
        const normalizedNodeName = nodeName.trim();

        if (!normalizedNodeName) {
            return {
                isValid: false,
                errorMessage: 'Node name cannot be empty.',
            };
        }

        // Find existing node with the same name
        const existingNode = nodes.find((node) => {
            // Skip the node being edited
            if (excludeNodeId && node.id === excludeNodeId) {
                return false;
            }
            return node.node_name?.trim() === normalizedNodeName;
        });

        if (existingNode) {
            return {
                isValid: false,
                errorMessage: `Node name "${normalizedNodeName}" is already in use.`,
                existingNode,
            };
        }

        return {
            isValid: true,
        };
    }

    /**
     * Gets all existing node names (useful for debugging or other purposes)
     * @param excludeNodeId - Optional node ID to exclude
     * @returns Array of existing node names
     */
    public getExistingNodeNames(excludeNodeId?: string): string[] {
        const nodes = this.flowService.nodes();
        return nodes
            .filter((node) => !excludeNodeId || node.id !== excludeNodeId)
            .map((node) => node.node_name?.trim())
            .filter((name) => name && name.length > 0);
    }

    /**
     * Checks if a node name is available
     * @param nodeName - The node name to check
     * @param excludeNodeId - Optional node ID to exclude
     * @returns boolean indicating if the name is available
     */
    public isNodeNameAvailable(nodeName: string, excludeNodeId?: string): boolean {
        return this.validateNodeName(nodeName, excludeNodeId).isValid;
    }

    /**
     * Gets the next available node name based on a base name
     * @param baseName - The base name to start with
     * @param excludeNodeId - Optional node ID to exclude
     * @returns The next available node name
     */
    public getNextAvailableNodeName(baseName: string, excludeNodeId?: string): string {
        const existingNames = this.getExistingNodeNames(excludeNodeId);
        const normalizedBaseName = baseName.trim();

        if (!existingNames.includes(normalizedBaseName)) {
            return normalizedBaseName;
        }

        let counter = 1;
        let candidateName = `${normalizedBaseName} ${counter}`;

        while (existingNames.includes(candidateName)) {
            counter++;
            candidateName = `${normalizedBaseName} ${counter}`;
        }

        return candidateName;
    }
}
