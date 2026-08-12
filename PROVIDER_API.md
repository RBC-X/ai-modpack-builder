# Provider API

All content sources implement one interface (`src/providers/types.ts`):

```ts
interface Provider {
  name: 'modrinth' | 'curseforge';
  available: boolean;
  unavailableReason?: string;

  search(opts: SearchOptions): Promise<ProviderProject[]>;
  getProject(projectId: string): Promise<ProviderProject | null>;
  getVersions(projectId: string, opts?: VersionFilter): Promise<ProviderVersion[]>;
  getDependencies(version: ProviderVersion): Promise<VersionDependency[]>;
  getDownloadFile(version: ProviderVersion): Promise<VersionFile | undefined>;
  getHashes(version: ProviderVersion): Promise<Record<string, string>>;
  manifestReference(projectId: string, version: ProviderVersion): Promise<unknown | null>;
}
```

`SearchOptions`: query, projectType (`mod | resourcepack | shader | datapack`),
minecraftVersion, loaders, categories (OR'd within one facet group), limit,
index.

`ProviderVersion` carries everything the solver needs: `gameVersions`,
`loaders`, `releaseChannel`, `files` (URL + size + hashes), and `dependencies`
with `kind` ∈ `required | optional | incompatible | embedded` plus optional
`versionRange` / pinned `versionId`.

## Modrinth (always available)

Real API: `https://api.modrinth.com/v2`

- Search facets: `project_type`, `versions:<mc>`, `categories:<loader>`,
  `categories:<tag>` (categories OR'd, other groups AND'd).
- Versions: `GET /project/{id}/version?game_versions=…&loaders=…` with
  client-side re-filtering.
- Dependencies are part of the version object (`dependencies[]` with
  `dependency_type` and `version_range`).
- Files have sha1/sha512 hashes; **direct downloads are permitted** and are
  bundled into packs (SHA1-verified at download time).

## CurseForge (requires an API key)

Real API: `https://api.curseforge.com/v1` (header `x-api-key`).

- Key sources, in order: `CF_API_KEY` env var → Settings page (stored in
  `workspace/config/settings.json`, never logged; the UI masks it).
- Without a key the provider is `available: false` with a clear reason; builds
  continue on Modrinth.
- Searches use `gameId=432`, `classId` (6 mods, 12 resource packs/shaders),
  `gameVersion`, `modLoaderType` (1 Forge, 4 Fabric, 5 Quilt, 6 NeoForge).
- Files expose `dependencies[]` (`relationType` 1 embedded, 2 optional,
  3 required, 5 incompatible, 6 include).
- **Distribution policy**: CurseForge content is *not* bundled. Exports use the
  manifest mechanism (`{ projectID, fileID }`), which launchers resolve at
  install time. Direct download is only attempted when
  `allowDirectDownloads` is explicitly enabled (single-machine use) via the
  official signed download-url endpoint.

## Response caching

Provider GETs are cached on disk under `workspace/cache/providers/` (TTL 6h)
with a **stale-on-error fallback** so a network blip degrades to cached data
instead of failing the build. Disable with `AMB_NO_CACHE=1` or tune with
`AMB_CACHE_TTL_SECONDS`.

## Retry behavior

`retryFetch` (src/core/util.ts) retries 500s and 429s with backoff honoring
`Retry-After`, and is used by every provider request.
