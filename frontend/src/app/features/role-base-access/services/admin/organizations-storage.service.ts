import { inject, Injectable, signal } from '@angular/core';
import { CreateOrganizationRequest, GetOrganizationResponse, UpdateOrganizationRequest } from '@shared/models';
import { StorageService } from '@shared/services';
import { catchError, delay, Observable, of, tap, throwError } from 'rxjs';
import { shareReplay } from 'rxjs/operators';

import { AdminOrganizationsService } from './organizations.service';

@Injectable({
    providedIn: 'root',
})
export class OrganizationsStorageService implements StorageService {
    private organizationsSignal = signal<GetOrganizationResponse[]>([]);
    private organizationsLoaded = signal<boolean>(false);
    public readonly organizations = this.organizationsSignal.asReadonly();
    public readonly isOrganizationsLoaded = this.organizationsLoaded.asReadonly();

    private readonly apiService = inject(AdminOrganizationsService);

    createOrganization(data: CreateOrganizationRequest): Observable<GetOrganizationResponse> {
        return this.apiService.createOrganization(data).pipe(
            tap((newOrg) => {
                this.organizationsSignal.update((orgs) => [...orgs, newOrg]);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    getOrganizations(forceRefresh = false): Observable<GetOrganizationResponse[]> {
        if (this.organizationsLoaded() && !forceRefresh) {
            return of(this.organizationsSignal());
        }
        return this.apiService.getOrganizations().pipe(
            tap((organizations) => {
                this.organizationsSignal.set(organizations);
                this.organizationsLoaded.set(true);
            }),
            delay(this.organizationsLoaded() ? 0 : 300),
            shareReplay(1),
            catchError((err) => {
                this.organizationsLoaded.set(false);
                return throwError(() => err);
            })
        );
    }

    updateOrganization(id: number, data: UpdateOrganizationRequest): Observable<GetOrganizationResponse> {
        return this.apiService.updateOrganization(id, data).pipe(
            tap((updated) => {
                this.updateOrganizationInCache(updated);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    deactivateOrganization(id: number): Observable<void> {
        return this.apiService.deactivateOrganization(id).pipe(
            tap(() => {
                this.setActiveInCache(id, false);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    reactivateOrganization(id: number): Observable<void> {
        return this.apiService.reactivateOrganization(id).pipe(
            tap(() => {
                this.setActiveInCache(id, true);
            }),
            catchError((err) => throwError(() => err))
        );
    }

    private updateOrganizationInCache(updated: GetOrganizationResponse): void {
        this.organizationsSignal.update((orgs) => {
            const index = orgs.findIndex((o) => o.id === updated.id);
            if (index >= 0) {
                orgs[index] = updated;
            } else {
                orgs.push(updated);
            }
            return [...orgs];
        });
    }

    clear(): void {
        this.organizationsSignal.set([]);
        this.organizationsLoaded.set(false);
    }

    private setActiveInCache(id: number, isActive: boolean): void {
        this.organizationsSignal.update((orgs) => {
            const index = orgs.findIndex((o) => o.id === id);
            if (index >= 0) {
                orgs[index] = { ...orgs[index], is_active: isActive };
            }
            return [...orgs];
        });
    }
}
