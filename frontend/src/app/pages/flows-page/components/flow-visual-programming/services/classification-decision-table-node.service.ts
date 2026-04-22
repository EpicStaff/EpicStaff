import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { PromptConfig } from '../../../../../visual-programming/core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../../visual-programming/core/models/decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../../../../../visual-programming/core/models/node.model';
import {
    CreateClassificationConditionGroupRequest,
    CreateClassificationDecisionTableNodeRequest,
    CreatePromptConfigRequest,
    GetClassificationDecisionTableNodeRequest,
} from '../models/classification-decision-table-node.model';

@Injectable({
    providedIn: 'root',
})
export class ClassificationDecisionTableNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'classification-decision-table-node/';
    }

    createNode(
        request: CreateClassificationDecisionTableNodeRequest
    ): Observable<GetClassificationDecisionTableNodeRequest> {
        return this.http.post<GetClassificationDecisionTableNodeRequest>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    getNodeById(id: number): Observable<GetClassificationDecisionTableNodeRequest> {
        return this.http.get<GetClassificationDecisionTableNodeRequest>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    deleteNode(id: string): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    updateNode(
        id: number,
        request: CreateClassificationDecisionTableNodeRequest
    ): Observable<GetClassificationDecisionTableNodeRequest> {
        return this.http.put<GetClassificationDecisionTableNodeRequest>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    buildCreatePayload(
        graphId: number,
        node: ClassificationDecisionTableNodeModel,
        resolveNodeName: (idOrName: string | null) => string | null
    ): CreateClassificationDecisionTableNodeRequest {
        const tableData = node.data?.table;

        const conditionGroups: CreateClassificationConditionGroupRequest[] = (tableData?.condition_groups || [])
            .sort(
                (a: ConditionGroup & { continue_flag?: boolean }, b: ConditionGroup & { continue_flag?: boolean }) =>
                    (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER)
            )
            .map((group: ConditionGroup & { continue_flag?: boolean }, index: number) => ({
                group_name: group.group_name,
                order: typeof group.order === 'number' ? group.order : index + 1,
                expression: group.expression || null,
                prompt_id: group.prompt_id || null,
                manipulation: group.manipulation || null,
                continue_flag: !!(group.continue_flag ?? group.continue),
                // TODO: resolve group.next_node UUID to backend integer ID when an ID resolver is available here.
                // The primary save path (save-graph.diff.ts buildClassificationDecisionTablePayload) handles this correctly.
                next_node_id: null,
                // route_code: group.route_code || null,  // TEMP: testing without route_code
                dock_visible: group.dock_visible !== false,
                field_expressions: this.serializeFieldExpressions(group.field_expressions || {}),
                field_manipulations: group.field_manipulations || {},
            }));

        const preComp = tableData?.pre_computation || {};
        const postComp = tableData?.post_computation || {};
        const preCodeValue = preComp.code || tableData?.pre_computation_code || '';
        const postCodeValue = postComp.code || tableData?.post_computation_code || '';

        return {
            graph: graphId,
            node_name: node.node_name,
            pre_python_code:
                preCodeValue.trim() === ''
                    ? null
                    : {
                          code: preCodeValue,
                          libraries: preComp.libraries || [],
                          entrypoint: 'main',
                          global_kwargs: {},
                      },
            pre_input_map: preComp.input_map || tableData?.pre_input_map || null,
            pre_output_variable_path: preComp.output_variable_path || tableData?.pre_output_variable_path || null,
            post_python_code:
                postCodeValue.trim() === ''
                    ? null
                    : {
                          code: postCodeValue,
                          libraries: postComp.libraries || [],
                          entrypoint: 'main',
                          global_kwargs: {},
                      },
            post_input_map: postComp.input_map || tableData?.post_input_map || null,
            post_output_variable_path: postComp.output_variable_path || tableData?.post_output_variable_path || null,
            prompt_configs: Object.entries((tableData?.prompts || {}) as Record<string, PromptConfig>).map(
                ([key, cfg]) =>
                    ({
                        prompt_key: key,
                        prompt_text: cfg.prompt_text ?? '',
                        llm_config: cfg.llm_config ?? null,
                        output_schema: cfg.output_schema ?? null,
                        result_variable: cfg.result_variable ?? '',
                        variable_mappings: cfg.variable_mappings ?? {},
                    }) as CreatePromptConfigRequest
            ),
            default_llm_config: tableData?.default_llm_config ?? null,
            default_next_node: resolveNodeName(tableData?.default_next_node),
            next_error_node: resolveNodeName(tableData?.next_error_node),
            condition_groups: conditionGroups,
        };
    }

    serializeFieldExpressions(fieldExpressions: Record<string, unknown>): Record<string, string> {
        const result: Record<string, string> = {};
        for (const [key, value] of Object.entries(fieldExpressions)) {
            if (typeof value === 'object' && value !== null && 'operator' in value) {
                const v = value as { operator?: string; field?: string; value?: unknown };
                const field = v.field || key;
                const op = v.operator || '==';
                const val = v.value;
                result[field] = typeof val === 'string' ? `${op} "${val}"` : `${op} ${val}`;
            } else {
                result[key] = String(value);
            }
        }
        return result;
    }
}
