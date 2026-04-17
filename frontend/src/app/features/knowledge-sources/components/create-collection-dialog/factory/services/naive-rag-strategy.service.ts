import { Injectable } from "@angular/core";
import { Observable } from "rxjs";
import { map, tap } from "rxjs/operators";
import { CreateNaiveRag } from "../../../../models/naive-rag.model";
import { NaiveRagService } from "../../../../services/naive-rag.service";
import { RagCreationStrategy } from "../interfaces/rag-creation-strategy.interface";
import { NaiveRagConfigurationComponent } from "../../../naive-rag-configuration/naive-rag-configuration.component";

@Injectable({
    providedIn: 'root'
})
export class NaiveRagStrategy implements RagCreationStrategy {
    private naiveRag!: CreateNaiveRag;

    constructor(private naiveRagService: NaiveRagService) {}

    create(collectionId: number, embedderId: number): Observable<boolean> {
        return this.naiveRagService.createRagForCollection(collectionId, embedderId).pipe(
            tap(res => this.naiveRag = res.naive_rag),
            map(() => true)
        );
    }

    startIndexing(): Observable<boolean> {
        const naiveRagId = this.naiveRag.naive_rag_id;

        return this.naiveRagService.startIndexing({
            rag_id: naiveRagId,
            rag_type: 'naive'
        }).pipe(map(() => true));
    }

    getConfigurationComponent() {
        return NaiveRagConfigurationComponent;
    }

    getConfigurationInputs(): Record<string, unknown> {
        const naiveRagId = this.naiveRag.naive_rag_id;

        return { naiveRagId: naiveRagId };
    }
}
