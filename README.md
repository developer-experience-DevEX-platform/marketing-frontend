# marketing-frontend

Frontend app for marketing

React + Vite website on S3 and CloudFront. There is no Kubernetes,
Dockerfile, or GitOps path.

```bash
npm ci
npm run verify
npm run dev
npm run build
```

`public/config.js` is the runtime API host (`API_BASE_URL`). Leave it
empty until the backend URL is known.

The first Release run only proves CI. Publish waits until
`STATIC_SITE_BUCKET` exists. Extra browser tests belong in this repo's
`.github/workflows/ci.yml`, not in the reusable Frontend CI workflow.
