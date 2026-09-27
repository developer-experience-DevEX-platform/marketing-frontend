# marketing-frontend

Frontend app for marketing

Owner: `group:default/developer-experience`

This page is the TechDocs home for the website. GitHub still uses the
repository README. Add any other page as a `.md` file under `docs/`;
MkDocs includes it automatically. Keep `index.md` as the homepage.

## Local

```bash
npm ci
npm run verify
npm run dev
```

`public/config.js` sets `API_BASE_URL` at runtime. Change that file after
publish if the API host changes; do not bake the URL into the Vite
bundle.

## Verify

`npm run verify` runs format, lint, and unit tests.

The first GitHub Release run after scaffold only proves CI. Site publish
waits until `STATIC_SITE_BUCKET` exists. Docs publish waits until
`TECHDOCS_S3_BUCKET` exists.

## Platform

- Website repository: https://github.com/developer-experience-DevEX-platform/marketing-frontend
- Infrastructure stack: https://github.com/developer-experience-DevEX-platform/platform-infrastructure/tree/main/services/marketing-frontend
