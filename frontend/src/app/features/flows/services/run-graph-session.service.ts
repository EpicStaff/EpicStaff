import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { CrewNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/crew-node.service';
import { ConfigService } from '../../../services/config/config.service';
import { FlowsApiService } from './flows-api.service';

interface RunGraphResponse {
    session_id: number;
}

@Injectable({
    providedIn: 'root',
})
export class RunGraphService {
    constructor(
        private http: HttpClient,
        private graphService: FlowsApiService,
        private crewNodeService: CrewNodeService,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl;
    }

    runGraph(graphId: number, initialState?: Record<string, unknown>): Observable<RunGraphResponse> {
        const url = `${this.apiUrl}run-session/`;
        const formData = new FormData();
        formData.append('graph_id', graphId.toString());
        formData.append('initial_state', JSON.stringify(initialState || {}));

        return this.http.post<RunGraphResponse>(url, formData);
    }

    /*
  runProject(projectId: number, initialState?: any): Observable<{ graphId: number; sessionId: number }> {
    // Create a new graph with the provided properties
    const graphRequest: CreateGraphDtoRequest = {
      name: 'automatically created',
      entry_point: 'Project-Node-1',
      description: '',
      metadata: {
        nodes: [],
        connections: [],
        groups: [],
      },
    };

    return this.graphService.createGraph(graphRequest).pipe(
      tap((graph) => console.log('Graph created:', graph)),
      switchMap((graph) =>
        this.crewNodeService
          .createCrewNode({
            node_name: 'Project-Node-1',
            graph: graph.id,
            crew_id: projectId,
          })
          .pipe(
            tap((crewNodeResponse) =>
              console.log('Crew node created:', crewNodeResponse)
            ),
            // Run the graph session and then map back to the created graph and session
            switchMap(() =>
              this.runGraph(graph.id, initialState).pipe(
                tap((response) =>
                  console.log(
                    'Graph run completed for graph id:',
                    graph.id,
                    'session id:',
                    response.session_id
                  )
                ),
                map((response) => ({
                  graphId: graph.id,
                  sessionId: response.session_id,
                }))
              )
            )
          )
      )
    );
  }
  */
}
