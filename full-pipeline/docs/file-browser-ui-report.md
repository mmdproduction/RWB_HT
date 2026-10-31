# Platform file browser UI

Implemented in `full-pipeline/frontend` only; generated application templates were not changed by this task.

## User-facing result

The run dashboard now has four Russian-language tabs: process, result, files, and business task. The existing dashboard and deployment/repository links remain. The result tab points to the full explorer and project ZIP instead of limiting the user to the legacy artifacts list.

The Files tab provides a responsive split folder tree and code preview with collapsible directories, path search, total/matched counts, full selected path, language, file type, size, numbered monospace lines, copy, individual download, and complete ZIP. Preview content is rendered through Angular text interpolation, without HTML injection or external content URLs. All request/download paths are built from the selected run ID and encoded relative file path. Dependency/build exclusions returned by the API are available in a disclosure. Restricted secret files remain listed but have no preview or download; binary files explain how to download them. Truncated previews are labeled.

The explorer exists for queued, active, failed, blocked, interrupted, and succeeded runs. It stays mounted when switching tabs to retain selection, search, and collapsed folders. Each existing active-detail refresh also refreshes file inventory, selected content, and specification; final/manual detail refreshes do the same. Selection uses full relative path. Initial preference is root requirements.md, then root app-spec.json, then the first viewable public file. Failed requests preserve the previously displayed files and selected content, and stale requests cannot overwrite a newer run/selection/specification.

The Business Task tab distinguishes the original run requirements from the parsed app-spec.json description of the planned product. It displays available businessGoal, primaryAction, uiMode, screens, outOfScope, requirements, assumptions, roles, workflows, and questions, including nested analysis fields. Older specifications fall back to summary and workflows. Missing information is not invented, and the interface explicitly avoids claiming that displaying a specification proves product compliance.

## API integration

- GET /api/runs/{id}/files
- GET /api/runs/{id}/files/content?path=...
- GET /api/runs/{id}/files/download?path=...
- GET /api/runs/{id}/download

The frontend uses the agreed inventory/content contracts in src/models.ts. It does not use arbitrary contentUrl/downloadUrl values as navigation targets.

## Verification and limits

Production Angular compilation: npm run build --prefix full-pipeline/frontend passed (strict TypeScript/template checks). Tests, browser QA, and generation were not run, as requested. Runtime behavior against the new API and visual layout in a browser have therefore not been exercised in this task. Syntax highlighting is intentionally omitted; code is safe plain text with line numbers.
