import { TestBed } from '@angular/core/testing';
import { Secret } from '@shared/models';
import { firstValueFrom, of, throwError } from 'rxjs';

import { SecretsApiService } from './secrets-api.service';
import { SecretsStorageService } from './secrets-storage.service';

const LIVE = { id: 1, name: 'OpenAI key', tail: 'abcd' } as Secret;
const BINNED = { id: 7, name: 'Old key' };

function setup(binned$ = of([BINNED])) {
    const api = {
        getSecrets: vi.fn().mockReturnValue(of([LIVE])),
        getBinnedSecrets: vi.fn().mockReturnValue(binned$),
        deleteSecret: vi.fn().mockReturnValue(of(undefined)),
    };
    TestBed.configureTestingModule({ providers: [{ provide: SecretsApiService, useValue: api }] });
    return { storage: TestBed.inject(SecretsStorageService), api };
}

describe('SecretsStorageService', () => {
    it('offers live secrets only, until a binned one is the picked value', async () => {
        const { storage } = setup();
        await firstValueFrom(storage.getSecrets());

        expect(storage.selectItems(null).map((item) => item.value)).toEqual([1]);
        expect(storage.selectItems([1, 7])).toEqual([
            { name: 'OpenAI key', value: 1, tip: '••••abcd' },
            { name: 'Old key (in the recycle bin)', value: 7 },
        ]);
        expect(storage.isBinned(7)).toBe(true);
    });

    it('keeps the live list when the recycle bin cannot be read', async () => {
        const { storage } = setup(throwError(() => new Error('forbidden')));

        expect(await firstValueFrom(storage.getSecrets())).toEqual([LIVE]);
        expect(storage.binnedSecrets()).toEqual([]);
    });

    it('moves a deleted secret to the recycle bin, so a picker still holding it names it', async () => {
        const { storage } = setup(of([]));
        await firstValueFrom(storage.getSecrets());

        await firstValueFrom(storage.deleteSecret(1));

        expect(storage.secrets()).toEqual([]);
        expect(storage.selectItems(1)).toEqual([{ name: 'OpenAI key (in the recycle bin)', value: 1 }]);
    });
});
