import { Injectable } from '@angular/core';
import { RUFF_DEFAULT_CONFIG } from '../constants/ruff-config.constants';
import type { RuffDiagnostic } from '../models/ruff-result.model';

@Injectable({
  providedIn: 'root',
})
export class RuffWasmService {
  private workspace: { check(contents: string): RuffDiagnostic[] } | null =
    null;
  private initPromise: Promise<void> | null = null;

  async init(): Promise<void> {
    if (this.workspace) {
      return;
    }
    if (this.initPromise) {
      return this.initPromise;
    }

    this.initPromise = (async () => {
      try {
        const ruff = await import('@astral-sh/ruff-wasm-web');
        const wasmUrl = new URL(
          'assets/ruff-wasm/ruff_wasm_bg.wasm',
          document.baseURI
        ).href;
        await ruff.default(wasmUrl);
        this.workspace = new ruff.Workspace(
          RUFF_DEFAULT_CONFIG as object,
          ruff.PositionEncoding.Utf16
        );
      } catch (err) {
        throw err;
      }
    })();

    return this.initPromise;
  }

  async check(code: string): Promise<RuffDiagnostic[]> {
    await this.init();
    if (!this.workspace) {
      return [];
    }
    return this.workspace.check(code) ?? [];
  }
}
